from datetime import datetime, timezone
from typing import Any

from crewai.tools import tool

from app.core.db import put_item, query_sk_prefix


def _log_meal_entry(
    user_id: str,
    meal_type: str,
    items: list[str],
    total_kcal: float,
    macros: dict[str, float],
) -> dict[str, Any]:
    """Write MEAL#<ts> record to DynamoDB; return confirmation + daily total."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_prefix = ts[:10]

    put_item(
        user_id=user_id,
        sk=f"MEAL#{ts}",
        data={
            "meal_type": meal_type,
            "items": items,
            "total_kcal": str(total_kcal),
            "macros": {k: str(v) for k, v in macros.items()},
            "logged_at": ts,
        },
    )

    daily_meals = query_sk_prefix(user_id, f"MEAL#{date_prefix}")
    daily_total = sum(float(m.get("total_kcal", 0)) for m in daily_meals)

    return {
        "status": "logged",
        "meal_type": meal_type,
        "kcal": total_kcal,
        "daily_total_kcal": round(daily_total, 1),
        "logged_at": ts,
    }


def _get_daily_calorie_log(user_id: str, date: str) -> dict[str, Any]:
    """Fetch all meals for a given date (YYYY-MM-DD) with total kcal."""
    meals = query_sk_prefix(user_id, f"MEAL#{date}")

    meal_list = [
        {
            "meal_type": m.get("meal_type"),
            "items": m.get("items", []),
            "kcal": float(m.get("total_kcal", 0)),
            "logged_at": m.get("logged_at"),
        }
        for m in meals
    ]

    return {
        "date": date,
        "meals": meal_list,
        "total_kcal": round(sum(m["kcal"] for m in meal_list), 1),
    }


@tool("log_meal_entry")
def log_meal_entry(
    user_id: str,
    meal_type: str,
    items: list[str],
    total_kcal: float,
    macros: dict[str, float],
) -> dict[str, Any]:
    """Log a meal to DynamoDB; returns confirmation and running daily kcal total."""
    return _log_meal_entry(user_id, meal_type, items, total_kcal, macros)


@tool("get_daily_calorie_log")
def get_daily_calorie_log(user_id: str, date: str) -> dict[str, Any]:
    """Return all meals logged for date (YYYY-MM-DD) with daily kcal sum."""
    return _get_daily_calorie_log(user_id, date)
