"""
Tests for generate_reports module.
"""

from yazio_exporter.generate_reports import (
    _daily_steps,
    _detect_active_range,
    _exercise_sessions,
    _extract_daily_records,
    _food_stats,
    _get_products_map,
    _session_type_stats,
    _time_of_day_split,
    _weekly_aggregate,
    generate_analysis,
    generate_llm_prompt,
)


def _make_day(kcal, protein=50, carbs=100, fat=40, products=None):
    """Helper to create a realistic day entry."""
    return {
        "daily_summary": {
            "meals": {
                "breakfast": {
                    "nutrients": {
                        "energy.energy": kcal * 0.3,
                        "nutrient.protein": protein * 0.3,
                        "nutrient.carb": carbs * 0.3,
                        "nutrient.fat": fat * 0.3,
                    }
                },
                "lunch": {
                    "nutrients": {
                        "energy.energy": kcal * 0.4,
                        "nutrient.protein": protein * 0.4,
                        "nutrient.carb": carbs * 0.4,
                        "nutrient.fat": fat * 0.4,
                    }
                },
                "dinner": {
                    "nutrients": {
                        "energy.energy": kcal * 0.3,
                        "nutrient.protein": protein * 0.3,
                        "nutrient.carb": carbs * 0.3,
                        "nutrient.fat": fat * 0.3,
                    }
                },
            },
            "goals": {"energy.energy": 2000},
        },
        "consumed": {"products": products or []},
    }


def _make_days_data():
    """Create a realistic multi-day dataset."""
    return {
        "2024-01-15": _make_day(1800, 120, 200, 60),
        "2024-01-16": _make_day(2100, 140, 220, 70),
        "2024-01-17": _make_day(1500, 100, 180, 50),
        "2024-01-18": _make_day(1900, 130, 210, 65),
        "2024-01-19": _make_day(2200, 150, 230, 75),
    }


def _make_weight_data():
    return {
        "2024-01-15": 80.0,
        "2024-01-17": 79.8,
        "2024-01-19": 79.5,
    }


def _make_products_data():
    return {
        "products": {
            "prod-1": {
                "name": "Oatmeal",
                "category": "grains",
                "nutrients": {"energy.energy": 3.5, "nutrient.protein": 0.12},
            },
            "prod-2": {
                "name": "Chicken Breast",
                "category": "meat",
                "nutrients": {"energy.energy": 1.65, "nutrient.protein": 0.31},
            },
        }
    }


def _make_profile_data():
    return {
        "body_height": 180,
        "sex": "male",
        "date_of_birth": "1990-05-15",
        "goal": "lose",
        "weight_change_per_week": -0.5,
        "diet": {"protein_percentage": 30, "carb_percentage": 40, "fat_percentage": 30},
    }


# ── generate_analysis tests ──


def test_generate_analysis_with_realistic_data():
    """generate_analysis returns markdown with expected sections."""
    result = generate_analysis(_make_days_data(), _make_weight_data(), _make_products_data(), _make_profile_data())

    assert result.startswith("# Nutrition Data Analysis")
    assert "## Overview" in result
    assert "## Calories" in result
    assert "## Macros" in result
    assert "## Day of Week" in result
    assert "## Top Foods" in result
    assert "## Extreme Days" in result
    assert "2024-01-15" in result


def test_generate_analysis_empty_data():
    """generate_analysis with empty data returns no-data message."""
    result = generate_analysis({}, {}, {}, {})
    assert "No tracked data" in result


def test_generate_analysis_all_below_threshold():
    """generate_analysis when all days are below 800 kcal."""
    days = {
        "2024-01-15": _make_day(500),
        "2024-01-16": _make_day(600),
    }
    result = generate_analysis(days, {}, {}, {})
    assert "No tracked data" in result or "No tracked days" in result


# ── generate_llm_prompt tests ──


def test_generate_llm_prompt_with_realistic_data():
    """generate_llm_prompt returns string with instructions and data."""
    result = generate_llm_prompt(_make_days_data(), _make_weight_data(), _make_products_data(), _make_profile_data())

    assert "sports nutritionist" in result
    assert "# Client Profile" in result
    assert "# Daily Data" in result or "# Weekly Data" in result
    assert "Top" in result
    assert "2024-01-15" in result


def test_generate_llm_prompt_empty_data():
    """generate_llm_prompt with empty data returns no-data message."""
    result = generate_llm_prompt({}, {}, {}, {})
    assert "No tracked data" in result


def test_generate_llm_prompt_all_below_threshold():
    """generate_llm_prompt when all days are below 800 kcal."""
    days = {
        "2024-01-15": _make_day(500),
        "2024-01-16": _make_day(600),
    }
    result = generate_llm_prompt(days, {}, {}, {})
    assert "No tracked" in result


# ── _detect_active_range tests ──


def test_detect_active_range_finds_correct_dates():
    """_detect_active_range returns first and last tracked dates."""
    days = _make_days_data()
    start, end = _detect_active_range(days)
    assert start == "2024-01-15"
    assert end == "2024-01-19"


def test_detect_active_range_all_below_threshold():
    """_detect_active_range returns (None, None) when all below 800 kcal."""
    days = {
        "2024-01-15": _make_day(500),
        "2024-01-16": _make_day(700),
    }
    start, end = _detect_active_range(days)
    assert start is None
    assert end is None


# ── _extract_daily_records tests ──


def test_extract_daily_records_correct_fields():
    """_extract_daily_records extracts expected fields."""
    days = _make_days_data()
    products = _make_products_data()["products"]
    records = _extract_daily_records(days, _make_weight_data(), products, "2024-01-15", "2024-01-19")

    assert len(records) == 5
    r = records[0]
    assert r["date"] == "2024-01-15"
    assert r["kcal"] == 1800
    assert r["protein"] == 120
    assert r["carbs"] == 200
    assert r["fat"] == 60
    assert r["weight"] == 80.0
    assert r["tracked"] is True
    assert "dow" in r
    assert "weekday" in r


# ── _food_stats tests ──


def test_food_stats_correct_aggregation():
    """_food_stats correctly counts frequency and calories."""
    products = _make_products_data()["products"]
    records = [
        {"products": [{"product_id": "prod-1", "amount": 100}], "tracked": True},
        {
            "products": [{"product_id": "prod-1", "amount": 50}, {"product_id": "prod-2", "amount": 200}],
            "tracked": True,
        },
    ]

    result = _food_stats(records, products, count=10)

    assert len(result) == 2
    oatmeal = next(f for f in result if f["name"] == "Oatmeal")
    assert oatmeal["count"] == 2
    assert oatmeal["total_kcal"] == round(3.5 * 100 + 3.5 * 50)
    assert oatmeal["category"] == "grains"

    chicken = next(f for f in result if f["name"] == "Chicken Breast")
    assert chicken["count"] == 1


# ── _weekly_aggregate tests ──


def test_weekly_aggregate_correct_rollup():
    """_weekly_aggregate produces correct weekly summaries."""
    days = _make_days_data()
    products = _make_products_data()["products"]
    records = _extract_daily_records(days, _make_weight_data(), products, "2024-01-15", "2024-01-19")

    weekly = _weekly_aggregate(records)
    assert len(weekly) == 1  # all within same week
    w = weekly[0]
    assert w["tracked"] == 5
    assert w["total"] == 5
    assert w["avg_kcal"] > 0


# ── _get_products_map tests ──


def test_get_products_map_nested_format():
    """_get_products_map unwraps nested {'products': {...}} format."""
    data = {"products": {"p1": {"name": "Test"}}, "recipes": {}}
    result = _get_products_map(data)
    assert "p1" in result
    assert result["p1"]["name"] == "Test"


def test_get_products_map_flat_format():
    """_get_products_map handles flat {pid: {...}} format."""
    data = {"p1": {"name": "Test"}}
    result = _get_products_map(data)
    assert "p1" in result
    assert result["p1"]["name"] == "Test"


def _make_session(date, name="strengthtraining", duration=15, energy=116.0):
    """Helper to create a training entry as returned by the exercises endpoint."""
    return {"date": date, "name": name, "duration": duration, "energy": energy}


def _make_days_with_exercise():
    """Multi-day dataset with training sessions inside and outside the tracked period."""
    days = _make_days_data()
    days["2024-01-15"]["exercises"] = {
        "training": [_make_session("2024-01-15 06:41:00")],
        "custom_training": [],
        "activity": {"steps": 8000},
    }
    days["2024-01-16"]["exercises"] = {
        "training": [_make_session("2024-01-16 19:45:00", duration=12, energy=92.0)],
        "custom_training": [_make_session("2024-01-16 13:00:00", name="running", duration=30, energy=332.0)],
        "activity": {"steps": 0},
    }
    days["2024-01-17"]["exercises"] = {
        "training": [{"date": None, "name": "hiit", "duration": 15, "energy": 148.0}],
        "custom_training": [],
        "activity": None,
    }
    # Day below the calorie threshold, outside the active range
    days["2023-12-01"] = _make_day(200)
    days["2023-12-01"]["exercises"] = {
        "training": [_make_session("2023-12-01 07:00:00")],
        "custom_training": [],
        "activity": {"steps": 5000},
    }
    return days


def test_exercise_sessions_splits_inside_and_outside_period():
    days = _make_days_with_exercise()
    sessions, outside = _exercise_sessions(days, "2024-01-15", "2024-01-19")

    assert len(sessions) == 4
    assert outside == 1
    assert [s["date"] for s in sessions] == ["2024-01-15", "2024-01-16", "2024-01-16", "2024-01-17"]
    assert sessions[0]["time"] == "06:41"
    assert sessions[0]["kcal"] == 116
    assert sessions[3]["time"] == ""


def test_exercise_sessions_includes_custom_training():
    days = _make_days_with_exercise()
    sessions, _ = _exercise_sessions(days, "2024-01-16", "2024-01-16")

    assert {s["name"] for s in sessions} == {"strengthtraining", "running"}


def test_exercise_sessions_handles_missing_exercises_key():
    days = _make_days_data()
    sessions, outside = _exercise_sessions(days, "2024-01-15", "2024-01-19")

    assert sessions == []
    assert outside == 0


def test_time_of_day_split_buckets_by_hour():
    sessions = [
        {"time": "06:41"},
        {"time": "11:59"},
        {"time": "12:00"},
        {"time": "17:59"},
        {"time": "18:00"},
        {"time": ""},
    ]
    split = _time_of_day_split(sessions)

    assert split == {"morning": 2, "afternoon": 2, "evening": 1, "unknown": 1}


def test_session_type_stats_aggregates_and_orders_by_frequency():
    sessions = [
        {"name": "running", "duration": 30, "kcal": 332},
        {"name": "strengthtraining", "duration": 15, "kcal": 116},
        {"name": "strengthtraining", "duration": 12, "kcal": 92},
    ]
    stats = _session_type_stats(sessions)

    assert stats[0] == {"name": "strengthtraining", "count": 2, "minutes": 27, "kcal": 208}
    assert stats[1] == {"name": "running", "count": 1, "minutes": 30, "kcal": 332}


def test_daily_steps_skips_zero_missing_and_out_of_range():
    days = _make_days_with_exercise()
    steps = _daily_steps(days, "2024-01-15", "2024-01-19")

    assert steps == [8000]


def test_generate_analysis_exercise_section_with_sessions():
    result = generate_analysis(_make_days_with_exercise(), {}, {}, {})

    assert "## Exercise" in result
    assert "- Sessions: 4 on 3/5 days (60%)" in result
    assert "- Volume: 72 min total, 18 min avg per session" in result
    assert "- Time of day: 1 morning / 1 afternoon / 1 evening / 1 unknown" in result
    assert "- Steps: 8000/day avg over 1 days with data" in result
    assert "- Outside this period: 1 sessions not counted above" in result
    assert "| strengthtraining | 2 | 27 | 208 |" in result
    assert "### Recent Sessions" in result
    assert "| 2024-01-15 | 06:41 | strengthtraining | 15 | 116 |" in result
    assert "| 2024-01-17 | ? | hiit | 15 | 148 |" in result


def test_generate_analysis_exercise_section_without_sessions():
    result = generate_analysis(_make_days_data(), {}, {}, {})

    assert "## Exercise" in result
    assert "- No training sessions logged in this period" in result
    assert "### Recent Sessions" not in result
