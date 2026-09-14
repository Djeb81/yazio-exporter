"""Tests for the daemon sync: rate limit, backoff, refresh, strict validation, window."""

import json
from datetime import date

import pytest
import responses

from yazio_exporter.auth import load_token_file, make_authenticated_client, save_token_file
from yazio_exporter.client import YazioClient
from yazio_exporter.exceptions import APIError, AuthenticationError, SchemaError
from yazio_exporter.sync import RateLimiter, sync, validate_consumed, validate_daily_summary

API = "https://yzapi.yazio.com/v15"


def test_rate_limiter_spaces_calls():
    clock = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        clock[0] += s

    limiter = RateLimiter(1.0, sleep=sleep, clock=lambda: clock[0])
    limiter()
    clock[0] += 0.2
    limiter()
    limiter()
    assert limiter.calls == 3
    assert [round(s, 3) for s in slept] == [0.8, 1.0]


@responses.activate
def test_client_backs_off_on_429_then_succeeds(monkeypatch):
    sleeps = []
    monkeypatch.setattr("yazio_exporter.client.time.sleep", lambda s: sleeps.append(s))
    responses.add(responses.GET, f"{API}/user", status=429, headers={"Retry-After": "7"})
    responses.add(responses.GET, f"{API}/user", json={"ok": True}, status=200)
    client = YazioClient()
    client.set_token("t")
    assert client.get("/user").json() == {"ok": True}
    assert sleeps == [7.0]


@responses.activate
def test_client_gives_up_after_repeated_429(monkeypatch):
    monkeypatch.setattr("yazio_exporter.client.time.sleep", lambda s: None)
    for _ in range(3):
        responses.add(responses.GET, f"{API}/user", status=429)
    client = YazioClient()
    client.set_token("t")
    with pytest.raises(APIError) as exc:
        client.get("/user")
    assert exc.value.status_code == 429


@responses.activate
def test_silent_refresh_on_401(tmp_path):
    token_file = tmp_path / "token.txt"
    save_token_file({"access_token": "old", "refresh_token": "r1"}, str(token_file))
    responses.add(responses.GET, f"{API}/user", status=401, json={"error": "expired"})
    responses.add(
        responses.POST, f"{API}/oauth/token", json={"access_token": "new", "refresh_token": "r2", "expires_in": 3600}
    )
    responses.add(responses.GET, f"{API}/user", json={"ok": True})
    client = make_authenticated_client(str(token_file))
    assert client.get("/user").json() == {"ok": True}
    assert client.session.headers["Authorization"] == "Bearer new"
    saved = load_token_file(str(token_file))
    assert saved["refresh_token"] == "r2" and "expires_at" in saved
    assert oct(token_file.stat().st_mode & 0o777) == "0o600"
    refresh_call = responses.calls[1].request
    assert refresh_call.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert "grant_type=refresh_token" in refresh_call.body


@responses.activate
def test_401_without_refresh_token_is_loud(tmp_path):
    token_file = tmp_path / "token.txt"
    token_file.write_text("legacy-plain-token")
    responses.add(responses.GET, f"{API}/user", status=401, json={"error": "expired"})
    client = make_authenticated_client(str(token_file))
    assert client.refresher is None
    with pytest.raises(AuthenticationError):
        client.get("/user")


def test_validation_rejects_unknown_structure():
    with pytest.raises(SchemaError, match=r"products\[0\]\.amount"):
        validate_consumed({"products": [{"id": "a", "product_id": "p", "daytime": "lunch", "amount": "12"}]}, "c")
    with pytest.raises(SchemaError, match="energy.energy missing"):
        validate_daily_summary({"meals": {"lunch": {"nutrients": {"nutrient.carb": 1}}}}, "s")
    assert validate_consumed({}, "c") == {"products": [], "recipe_portions": [], "simple_products": []}


def _day_payloads(day: str, kcal: float = 2000.0):
    responses.add(
        responses.GET,
        f"{API}/user/consumed-items?date={day}",
        json={
            "products": [
                {
                    "id": f"i-{day}",
                    "product_id": "p1",
                    "daytime": "lunch",
                    "amount": 100,
                    "serving": "gram",
                    "serving_quantity": 100,
                    "type": "product",
                    "date": f"{day} 12:00:00",
                }
            ],
            "recipe_portions": [],
            "simple_products": [],
        },
    )
    responses.add(
        responses.GET,
        f"{API}/user/widgets/daily-summary?date={day}",
        json={
            "meals": {
                "lunch": {
                    "nutrients": {
                        "energy.energy": kcal,
                        "nutrient.protein": 100,
                        "nutrient.carb": 200,
                        "nutrient.fat": 50,
                    }
                }
            },
            "goals": {"energy.energy": 2300},
        },
    )
    responses.add(
        responses.GET,
        f"{API}/user/exercises?date={day}",
        json={"training": [], "custom_training": [], "activity": None},
    )
    responses.add(responses.GET, f"{API}/user/goals?date={day}", json={"energy.energy": 2300})
    responses.add(responses.GET, f"{API}/user/water-intake?date={day}", json={"water_intake": 1500})
    responses.add(responses.GET, f"{API}/user/bodyvalues/weight/last?date={day}", json={"value": 97.4, "date": day})


def _client():
    client = YazioClient()
    client.set_token("t")
    client.throttle = RateLimiter(0.0)
    return client


@responses.activate
def test_sync_first_run_discovers_and_writes(tmp_path):
    responses.add(
        responses.GET,
        f"{API}/user/consumed-items/nutrients-daily",
        json=[{"date": "2026-09-12"}, {"date": "2026-09-13"}],
    )
    for d in ("2026-09-12", "2026-09-13"):
        _day_payloads(d)
    responses.add(
        responses.GET,
        f"{API}/products/p1",
        json={
            "name": "Riz",
            "category": "riceproducts",
            "base_unit": "g",
            "nutrients": {"energy.energy": 1.3},
            "producer": None,
        },
    )
    stats = sync(_client(), str(tmp_path), today=date(2026, 9, 14))
    assert stats == {"discovered": 2, "fetched": 2, "products_added": 1, "days_total": 2}
    days = json.loads((tmp_path / "days.json").read_text())
    assert set(days) == {"2026-09-12", "2026-09-13"}
    assert days["2026-09-12"]["fetched_at"].endswith("Z")
    assert json.loads((tmp_path / "weight.json").read_text()) == {"2026-09-12": 97.4, "2026-09-13": 97.4}
    assert "p1" in json.loads((tmp_path / "products.json").read_text())["products"]
    assert oct((tmp_path / "days.json").stat().st_mode & 0o777) == "0o600"


@responses.activate
def test_sync_refetches_window_and_freezes_older_days(tmp_path):
    (tmp_path / "days.json").write_text(
        json.dumps(
            {
                "2026-09-01": {
                    "consumed": {"products": []},
                    "daily_summary": {"meals": {}},
                    "fetched_at": "2026-09-02T00:00:00Z",
                },
                "2026-09-12": {
                    "consumed": {"products": []},
                    "daily_summary": {"meals": {}},
                    "fetched_at": "2026-09-13T00:00:00Z",
                },
            }
        )
    )
    (tmp_path / "products.json").write_text(json.dumps({"products": {"p1": {}}, "recipes": {}}))
    responses.add(
        responses.GET,
        f"{API}/user/consumed-items/nutrients-daily",
        json=[{"date": "2026-09-11"}, {"date": "2026-09-12"}, {"date": "2026-09-13"}],
    )
    for d in ("2026-09-11", "2026-09-12", "2026-09-13"):
        _day_payloads(d)
    stats = sync(_client(), str(tmp_path), window_days=3, today=date(2026, 9, 14))
    assert stats["fetched"] == 3 and stats["days_total"] == 4
    days = json.loads((tmp_path / "days.json").read_text())
    assert days["2026-09-01"]["fetched_at"] == "2026-09-02T00:00:00Z"  # frozen
    assert days["2026-09-12"]["fetched_at"] != "2026-09-13T00:00:00Z"  # inside the window: refreshed
    assert (tmp_path / "days.json.bak").exists()
    discovery = [c.request.url for c in responses.calls if "nutrients-daily" in c.request.url]
    assert discovery == [f"{API}/user/consumed-items/nutrients-daily?start=2026-09-01&end=2026-09-14"]


@responses.activate
def test_sync_schema_error_writes_nothing(tmp_path):
    (tmp_path / "days.json").write_text(json.dumps({"2026-09-01": {"fetched_at": "x"}}))
    responses.add(responses.GET, f"{API}/user/consumed-items/nutrients-daily", json=[{"date": "2026-09-13"}])
    responses.add(
        responses.GET,
        f"{API}/user/consumed-items?date=2026-09-13",
        json={"products": [{"id": "i", "product_id": "p", "daytime": "lunch"}]},
    )
    with pytest.raises(SchemaError, match="amount"):
        sync(_client(), str(tmp_path), today=date(2026, 9, 14))
    assert json.loads((tmp_path / "days.json").read_text()) == {"2026-09-01": {"fetched_at": "x"}}
    assert not (tmp_path / "days.json.bak").exists()


@responses.activate
def test_sync_is_sequential_and_throttled(tmp_path):
    # Seeded: discovery covers the window only (1 request) instead of 5 years of months.
    (tmp_path / "days.json").write_text(json.dumps({"2026-08-01": {"fetched_at": "x"}}))
    responses.add(responses.GET, f"{API}/user/consumed-items/nutrients-daily", json=[{"date": "2026-09-13"}])
    _day_payloads("2026-09-13")
    responses.add(
        responses.GET,
        f"{API}/products/p1",
        json={"name": "Riz", "category": "x", "base_unit": "g", "nutrients": {"energy.energy": 1.3}},
    )
    client = _client()
    limiter = RateLimiter(1.0, sleep=lambda s: None, clock=lambda: 0.0)
    client.throttle = limiter
    sync(client, str(tmp_path), today=date(2026, 9, 14))
    assert limiter.calls == len(responses.calls) == 8  # discovery + 5 day calls + product + weight
