"""
Incremental, rate-limited, validated synchronisation for a daemon run.

Rules (Phoenix SPEC.md § 3.1 A):
- one request per second at most, sequential, backoff on 429 / 5xx (client);
- every response is validated; an unexpected structure raises SchemaError and
  nothing is written;
- each run re-fetches the last `window_days` days and every never-seen day;
  older days are frozen unless `refresh` is set; each day carries `fetched_at`;
- files are written atomically at the end, previous days.json kept as .bak.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from yazio_exporter.client import YazioClient
from yazio_exporter.constants import DISCOVERY_LOOKBACK_YEARS, SYNC_MIN_INTERVAL_SECONDS, SYNC_WINDOW_DAYS
from yazio_exporter.exceptions import SchemaError
from yazio_exporter.utils import print_stderr

NUTRIENT_KEYS = ("energy.energy", "nutrient.protein", "nutrient.carb", "nutrient.fat")


class RateLimiter:
    """Blocks so that two calls are never closer than `min_interval` seconds."""

    def __init__(self, min_interval: float = SYNC_MIN_INTERVAL_SECONDS, sleep=time.sleep, clock=time.monotonic):
        self.min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None
        self.calls = 0

    def __call__(self) -> None:
        now = self._clock()
        if self._last is not None:
            wait = self.min_interval - (now - self._last)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last = now
        self.calls += 1


# ---------- validation ----------


def _require(cond: bool, path: str, message: str) -> None:
    if not cond:
        raise SchemaError(f"{path}: {message}")


def validate_consumed(data: Any, path: str) -> dict[str, list]:
    _require(isinstance(data, dict), path, "object expected")
    out: dict[str, list] = {}
    for key in ("products", "recipe_portions", "simple_products"):
        items = data.get(key, [])
        _require(isinstance(items, list), f"{path}.{key}", "list expected")
        out[key] = items
    for i, item in enumerate(out["products"]):
        ipath = f"{path}.products[{i}]"
        _require(isinstance(item, dict), ipath, "object expected")
        for key in ("id", "product_id", "daytime"):
            _require(isinstance(item.get(key), str) and item[key] != "", f"{ipath}.{key}", "non-empty string expected")
        _require(isinstance(item.get("amount"), int | float), f"{ipath}.amount", "number expected")
    return out


def validate_daily_summary(data: Any, path: str) -> dict[str, Any]:
    _require(isinstance(data, dict), path, "object expected")
    meals = data.get("meals")
    _require(isinstance(meals, dict), f"{path}.meals", "object expected")
    for meal, body in meals.items():
        _require(isinstance(body, dict), f"{path}.meals.{meal}", "object expected")
        nutrients = body.get("nutrients")
        _require(isinstance(nutrients, dict), f"{path}.meals.{meal}.nutrients", "object expected")
        _require("energy.energy" in nutrients, f"{path}.meals.{meal}.nutrients", "energy.energy missing")
        for key in NUTRIENT_KEYS:
            if key in nutrients:
                _require(
                    isinstance(nutrients[key], int | float), f"{path}.meals.{meal}.nutrients.{key}", "number expected"
                )
    return data


def validate_product(data: Any, path: str) -> dict[str, Any]:
    _require(isinstance(data, dict), path, "object expected")
    _require(isinstance(data.get("name"), str) and data["name"] != "", f"{path}.name", "non-empty string expected")
    _require(isinstance(data.get("category"), str), f"{path}.category", "string expected")
    _require(data.get("base_unit") in ("g", "ml"), f"{path}.base_unit", "g or ml expected")
    nutrients = data.get("nutrients")
    _require(isinstance(nutrients, dict), f"{path}.nutrients", "object expected")
    _require(
        isinstance(nutrients.get("energy.energy"), int | float), f"{path}.nutrients.energy.energy", "number expected"
    )
    return data


def validate_weight(data: Any, path: str) -> float | None:
    if data is None:
        return None
    _require(isinstance(data, dict), path, "object expected")
    value = data.get("value")
    if value is None:
        return None
    _require(isinstance(value, int | float), f"{path}.value", "number expected")
    return float(value)


# ---------- fetching ----------


def _get_json(client: YazioClient, endpoint: str) -> Any:
    response = client.get(endpoint)
    try:
        return response.json()
    except ValueError as e:
        raise SchemaError(f"{endpoint}: body is not JSON") from e


def fetch_day(client: YazioClient, day: str, fetched_at: str) -> dict[str, Any]:
    """Fetch and validate one day (5 requests)."""
    consumed = validate_consumed(_get_json(client, f"/user/consumed-items?date={day}"), f"consumed-items[{day}]")
    summary = validate_daily_summary(
        _get_json(client, f"/user/widgets/daily-summary?date={day}"), f"daily-summary[{day}]"
    )
    exercises = _get_json(client, f"/user/exercises?date={day}")
    _require(isinstance(exercises, dict), f"exercises[{day}]", "object expected")
    goals = _get_json(client, f"/user/goals?date={day}")
    _require(isinstance(goals, dict), f"goals[{day}]", "object expected")
    water = _get_json(client, f"/user/water-intake?date={day}")
    _require(isinstance(water, dict), f"water-intake[{day}]", "object expected")
    return {
        "consumed": consumed,
        "daily_summary": {
            "meals": summary["meals"],
            "activity_energy": summary.get("activity_energy"),
            "steps": summary.get("steps"),
            "water_intake": summary.get("water_intake"),
            "goals": summary.get("goals", {}),
            "units": summary.get("units", {}),
        },
        "exercises": {
            "training": exercises.get("training", []),
            "custom_training": exercises.get("custom_training", []),
            "activity": exercises.get("activity"),
        },
        "goals": {"data": goals},
        "water": {
            "water_intake": water.get("water_intake", 0),
            "gateway": water.get("gateway"),
            "source": water.get("source"),
        },
        "fetched_at": fetched_at,
    }


def discover_dates(client: YazioClient, start: date, end: date) -> list[str]:
    """Dates with data between start and end, month by month (1 request per month)."""
    dates: list[str] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        next_month = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
        last = min(next_month - timedelta(days=1), end)
        data = _get_json(
            client, f"/user/consumed-items/nutrients-daily?start={cursor.isoformat()}&end={last.isoformat()}"
        )
        _require(isinstance(data, list), f"nutrients-daily[{cursor.isoformat()}]", "list expected")
        for entry in data:
            _require(
                isinstance(entry, dict) and isinstance(entry.get("date"), str), "nutrients-daily", "entry.date expected"
            )
            if start.isoformat() <= entry["date"] <= end.isoformat():
                dates.append(entry["date"])
        cursor = next_month
    return sorted(set(dates))


# ---------- files ----------


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with open(path) as f:
        return json.load(f)


def _write_atomic(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    if path.exists():
        os.replace(path, path.with_suffix(path.suffix + ".bak"))
    os.replace(tmp, path)


# ---------- sync ----------


def sync(
    client: YazioClient,
    output_dir: str,
    window_days: int = SYNC_WINDOW_DAYS,
    refresh: bool = False,
    today: date | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """
    Run one synchronisation. Raises SchemaError / APIError / AuthenticationError
    before writing anything.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    today = today or date.today()
    now = now or datetime.now(UTC)
    fetched_at = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    days: dict[str, Any] = _load_json(out / "days.json", {})
    products: dict[str, Any] = _load_json(out / "products.json", {"products": {}, "recipes": {}})
    weight: dict[str, float] = _load_json(out / "weight.json", {})
    products.setdefault("products", {})
    products.setdefault("recipes", {})

    window_start = today - timedelta(days=window_days)
    discovery_start = date(today.year - DISCOVERY_LOOKBACK_YEARS, 1, 1) if refresh or not days else window_start
    discovered = discover_dates(client, discovery_start, today)

    to_fetch = [d for d in discovered if refresh or d not in days or d >= window_start.isoformat()]
    print_stderr(f"sync: {len(discovered)} days discovered, {len(to_fetch)} to fetch (window {window_days} d)")

    new_days: dict[str, Any] = {}
    for d in to_fetch:
        new_days[d] = fetch_day(client, d, fetched_at)

    product_ids = {
        item["product_id"]
        for day in new_days.values()
        for item in day["consumed"]["products"]
        if item["product_id"] not in products["products"]
    }
    for pid in sorted(product_ids):
        products["products"][pid] = validate_product(_get_json(client, f"/products/{pid}"), f"products[{pid}]")

    for d in to_fetch:
        value = validate_weight(_get_json(client, f"/user/bodyvalues/weight/last?date={d}"), f"weight[{d}]")
        if value is not None:
            weight[d] = value

    days.update(new_days)
    _write_atomic(out / "days.json", days)
    _write_atomic(out / "products.json", products)
    _write_atomic(out / "weight.json", weight)

    stats = {
        "discovered": len(discovered),
        "fetched": len(to_fetch),
        "products_added": len(product_ids),
        "days_total": len(days),
    }
    print_stderr(
        f"sync: {stats['fetched']} days written, {stats['products_added']} products added, "
        f"{stats['days_total']} days total"
    )
    return stats
