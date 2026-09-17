#!/usr/bin/env python3
"""
Consolidate the yazio-exporter output into a single self-documenting JSON file
suitable for feeding a Cowork/LLM project as knowledge.

Usage:  python3 tools/build_dataset.py [--out FILE]

Reads days.json, weight.json, products.json, profile.json, nutrients.json from
the same directory. Strips personal identifiers from the profile. Embeds the
known data caveats next to the data so a downstream agent cannot miss them.
"""

import argparse
import csv
import json
import os
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

D = Path(os.environ.get("YAZIO_EXPORT_DIR", Path.home() / "yazio-export")).expanduser()
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MIN_KCAL = 800
LOW_STEPS = 2000

# Personal identifiers never written to the dataset.
PROFILE_DROP = {
    "email",
    "user_token",
    "uuid",
    "stripe_customer_id",
    "siwa_user_id",
    "first_name",
    "last_name",
    "city",
    "profile_image",
    "login_type",
    "email_confirmation_status",
    "newsletter_opt_in",
    "tags",
    "date_of_birth",
}


def load(name):
    with open(D / name) as f:
        return json.load(f)


def nutr(meals, key):
    return sum((m.get("nutrients") or {}).get(key, 0) or 0 for m in meals.values())


def build():
    days = load("days.json")
    weight = load("weight.json")
    products = load("products.json").get("products", {})
    profile = load("profile.json")
    nutrients = load("nutrients.json")

    today = datetime.now(UTC).strftime("%Y-%m-%d")

    # ── real weigh-ins: weight.json carries the last known value forward ──
    weigh_ins, prev = [], None
    for d in sorted(weight):
        w = weight[d]
        if w is not None and w != prev:
            weigh_ins.append({"date": d, "weight_kg": w})
            prev = w

    # ── nutrients pivoted to date -> nutrient_id -> value ──
    by_date = defaultdict(dict)
    for nid, series in nutrients.items():
        for d, v in series.items():
            by_date[d][nid] = v

    # ── daily rows ──
    daily, sessions = [], []
    for d in sorted(days):
        di = days[d]
        meals = (di.get("daily_summary") or {}).get("meals") or {}
        ds = di.get("daily_summary") or {}
        goals = ((di.get("goals") or {}).get("data")) or {}
        ex = di.get("exercises") or {}
        todays = (ex.get("training") or []) + (ex.get("custom_training") or [])
        for t in todays:
            stamp = t.get("date") or ""
            sessions.append(
                {
                    "date": d,
                    "time": stamp[11:16] or None,
                    "type": t.get("name"),
                    "duration_min": t.get("duration") or 0,
                    "kcal": round(t.get("energy") or 0),
                    "note": t.get("note") or None,
                    "source": t.get("source") or t.get("gateway"),
                }
            )
        steps = ds.get("steps") or 0
        kcal = round(nutr(meals, "energy.energy"))
        daily.append(
            {
                "date": d,
                "weekday": DOW[datetime.strptime(d, "%Y-%m-%d").weekday()],
                "partial": d == today,
                "below_tracking_threshold": kcal < MIN_KCAL,
                "kcal": kcal,
                "protein_g": round(nutr(meals, "nutrient.protein")),
                "carbs_g": round(nutr(meals, "nutrient.carb")),
                "fat_g": round(nutr(meals, "nutrient.fat")),
                "meal_kcal": {
                    m: round((v.get("nutrients") or {}).get("energy.energy", 0) or 0) for m, v in sorted(meals.items())
                },
                "goal_kcal": round(goals.get("energy.energy") or 0),
                "goal_protein_g": round(goals.get("nutrient.protein") or 0),
                "water_ml": round((di.get("water") or {}).get("water_intake") or 0),
                "goal_water_ml": round(goals.get("water") or 0),
                "steps": steps,
                "steps_suspect": 0 < steps < LOW_STEPS,
                "goal_steps": round(goals.get("activity.step") or 0),
                "activity_kcal": round(ds.get("activity_energy") or 0),
                "sport_min": sum(t.get("duration") or 0 for t in todays),
                "sport_kcal": round(sum(t.get("energy") or 0 for t in todays)),
                "weigh_in_kg": next((w["weight_kg"] for w in weigh_ins if w["date"] == d), None),
                "weight_carried_kg": weight.get(d),
                "micronutrients": by_date.get(d) or None,
                "fetched_at": di.get("fetched_at"),
            }
        )

    # ── food aggregation ──
    freq, fkcal, fprot = defaultdict(int), defaultdict(float), defaultdict(float)
    for d in sorted(days):
        for p in (days[d].get("consumed") or {}).get("products") or []:
            pid = p.get("product_id")
            amt = p.get("amount") or 0
            pr = products.get(pid) or {}
            n = pr.get("nutrients") or {}
            freq[pid] += 1
            fkcal[pid] += (n.get("energy.energy", 0) or 0) * amt
            fprot[pid] += (n.get("nutrient.protein", 0) or 0) * amt
    foods = sorted(
        (
            {
                "product_id": pid,
                "name": (products.get(pid) or {}).get("name", "unknown"),
                "category": (products.get(pid) or {}).get("category"),
                "times": c,
                "total_kcal": round(fkcal[pid]),
                "total_protein_g": round(fprot[pid]),
            }
            for pid, c in freq.items()
        ),
        key=lambda x: (-x["times"], -x["total_kcal"]),
    )

    # ── metrics, computed twice: with and without the in-progress day ──
    def agg(rows):
        if not rows:
            return None
        k = [r["kcal"] for r in rows]
        return {
            "days": len(rows),
            "date_range": [rows[0]["date"], rows[-1]["date"]],
            "kcal_mean": round(statistics.mean(k)),
            "kcal_median": round(statistics.median(k)),
            "kcal_stdev": round(statistics.stdev(k)) if len(k) > 1 else 0,
            "protein_g_mean": round(statistics.mean(r["protein_g"] for r in rows)),
            "carbs_g_mean": round(statistics.mean(r["carbs_g"] for r in rows)),
            "fat_g_mean": round(statistics.mean(r["fat_g"] for r in rows)),
            "steps_mean": round(statistics.mean(r["steps"] for r in rows)),
            "days_under_goal": sum(1 for r in rows if r["goal_kcal"] and r["kcal"] <= r["goal_kcal"]),
            "days_with_goal": sum(1 for r in rows if r["goal_kcal"]),
        }

    tracked = [r for r in daily if not r["below_tracking_threshold"]]
    recent = [r for r in tracked if r["date"] >= "2026-08-31"]
    sess_recent = [s for s in sessions if s["date"] >= "2026-08-31"]

    u = profile["user"]
    prof = {k: v for k, v in u.items() if k not in PROFILE_DROP}
    prof["age_years"] = round(
        (datetime.now(UTC) - datetime.strptime(u["date_of_birth"][:10], "%Y-%m-%d").replace(tzinfo=UTC)).days / 365.25
    )
    prof["settings"] = profile.get("settings")
    prof["dietary_preferences"] = profile.get("dietary_preferences")

    dataset = {
        "_readme": {
            "what": "Yazio nutrition, body and activity export, consolidated for downstream analysis.",
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "generator": "tools/build_dataset.py (yazio-exporter local fork)",
            "units": {"energy": "kcal", "mass": "kg", "length": "cm", "serving": "g", "water": "ml"},
            "how_to_use": [
                "`daily` is the primary table, one row per calendar day, chronological.",
                "Prefer `metrics.recent_excluding_partial` over `metrics.recent_all` when comparing averages: the "
                "in-progress day drags them down.",
                "Use `weigh_ins` for weight analysis, never the per-day `weight_carried_kg`.",
            ],
            "caveats": [
                "WEIGHT CARRY-FORWARD: the Yazio endpoint returns the last known weight for every date, so "
                "`weight_carried_kg` repeats a stale value on days with no measurement. Only `weigh_ins` (value "
                "changes) are real measurements. There are very few of them; any weight trend computed from the "
                "carried series is an artefact.",
                "PARTIAL DAY: the row where `partial` is true is today, still being logged. It is real but incomplete. "
                "Excluded from `metrics.*_excluding_partial`.",
                "TRACKING THRESHOLD: rows with `below_tracking_threshold` true are under 800 kcal and represent days "
                "the user barely logged, not days they barely ate.",
                "HISTORY GAP: tracking ran 2025-04-16/17, then stopped until 2026-08-31. Do not interpolate across "
                "that 16-month gap.",
                "STEP SENSOR: `steps_suspect` marks days under 2000 steps, where the phone was likely not carried. "
                "Treat as missing, not as inactivity.",
                "MICRONUTRIENT UNITS: values are returned raw by the Yazio API, which does not declare a unit per "
                "nutrient. Do not assume mg vs g without verifying against a known product.",
                "TDEE: no reliable estimate is possible yet. The daily-weight series needed to separate fat change "
                "from water shifts does not exist. Any single TDEE number in older reports is provisional.",
            ],
            "privacy": (
                "Account identifiers, name, date of birth and payment fields are stripped from "
                "`profile`; only age_years is kept. The file still contains detailed health data."
            ),
        },
        "profile": prof,
        "metrics": {
            "all_tracked": agg(tracked),
            "recent_all": agg(recent),
            "recent_excluding_partial": agg([r for r in recent if not r["partial"]]),
            "activity_recent": {
                "sessions": len(sess_recent),
                "total_min": sum(s["duration_min"] for s in sess_recent),
                "total_kcal": sum(s["kcal"] for s in sess_recent),
                "morning_sessions": sum(1 for s in sess_recent if s["time"] and s["time"] < "12:00"),
                "by_type": {
                    t: {
                        "sessions": sum(1 for s in sess_recent if s["type"] == t),
                        "min": sum(s["duration_min"] for s in sess_recent if s["type"] == t),
                        "kcal": sum(s["kcal"] for s in sess_recent if s["type"] == t),
                    }
                    for t in sorted({s["type"] for s in sess_recent})
                },
            },
            "weight": {
                "real_weigh_ins": len(weigh_ins),
                "first": weigh_ins[0] if weigh_ins else None,
                "latest": weigh_ins[-1] if weigh_ins else None,
                "recent_weigh_ins": [w for w in weigh_ins if w["date"] >= "2026-08-31"],
            },
        },
        "weigh_ins": weigh_ins,
        "sessions": sessions,
        "daily": daily,
        "foods": foods,
    }
    return dataset


def write_csvs(data, outdir):
    """Emit one flat CSV per table. Nested fields are flattened, not dropped."""
    outdir.mkdir(parents=True, exist_ok=True)
    written = []

    meals = sorted({m for r in data["daily"] for m in r["meal_kcal"]})
    daily_cols = [
        "date",
        "weekday",
        "partial",
        "below_tracking_threshold",
        "kcal",
        "protein_g",
        "carbs_g",
        "fat_g",
        *[f"{m}_kcal" for m in meals],
        "goal_kcal",
        "goal_protein_g",
        "water_ml",
        "goal_water_ml",
        "steps",
        "steps_suspect",
        "goal_steps",
        "activity_kcal",
        "sport_min",
        "sport_kcal",
        "weigh_in_kg",
        "weight_carried_kg",
        "fetched_at",
    ]

    def daily_row(r):
        out = {c: r.get(c) for c in daily_cols if not c.endswith("_kcal") or c in r}
        for m in meals:
            out[f"{m}_kcal"] = r["meal_kcal"].get(m)
        return [out.get(c) for c in daily_cols]

    tables = {
        "daily.csv": (daily_cols, [daily_row(r) for r in data["daily"]]),
        "sessions.csv": (
            ["date", "time", "type", "duration_min", "kcal", "source", "note"],
            [
                [s["date"], s["time"], s["type"], s["duration_min"], s["kcal"], s["source"], s["note"]]
                for s in data["sessions"]
            ],
        ),
        "weigh_ins.csv": (
            ["date", "weight_kg"],
            [[w["date"], w["weight_kg"]] for w in data["weigh_ins"]],
        ),
        "foods.csv": (
            ["name", "category", "times", "total_kcal", "total_protein_g", "product_id"],
            [
                [f["name"], f["category"], f["times"], f["total_kcal"], f["total_protein_g"], f["product_id"]]
                for f in data["foods"]
            ],
        ),
        "micronutrients.csv": (
            ["date", "nutrient_id", "value"],
            [
                [r["date"], nid, val]
                for r in data["daily"]
                if r["micronutrients"]
                for nid, val in sorted(r["micronutrients"].items())
            ],
        ),
    }

    for name, (cols, rows) in tables.items():
        path = outdir / name
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for row in rows:
                w.writerow(["" if v is None else v for v in row])
        path.chmod(0o600)
        written.append((name, len(rows), path.stat().st_size))
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(D / "yazio-dataset.json"))
    ap.add_argument("--csv-dir", default=str(D / "csv"))
    ap.add_argument("--no-csv", action="store_true")
    args = ap.parse_args()
    data = build()
    out = Path(args.out)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    out.chmod(0o600)
    print(f"{out}  {out.stat().st_size} bytes")
    print(
        f"daily={len(data['daily'])} sessions={len(data['sessions'])} "
        f"weigh_ins={len(data['weigh_ins'])} foods={len(data['foods'])}"
    )
    if not args.no_csv:
        for name, rows, size in write_csvs(data, Path(args.csv_dir)):
            print(f"  {name:22} {rows:5} rows  {size:7} bytes")
