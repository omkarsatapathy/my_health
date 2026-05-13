from datetime import datetime, timedelta, timezone
from typing import Any

from crewai.tools import tool

from app.core.db import query_sk_prefix
from app.agents.physician.tools.weight_tools import _get_weight_trend
from app.agents.motivation.tools.streak_tools import _get_streak_data


def _date_from_sk(item: dict) -> str:
    return item.get("sk", "").split("#", 1)[-1][:10]


def _calorie_balance(user_id: str, start_iso: str, end_iso: str, days: int) -> dict[str, Any]:
    meals = [
        m for m in query_sk_prefix(user_id, "MEAL#")
        if start_iso <= _date_from_sk(m) <= end_iso
    ]
    workouts = [
        w for w in query_sk_prefix(user_id, "WORKOUT#")
        if start_iso <= _date_from_sk(w) <= end_iso
    ]
    total_in = sum(float(m.get("total_kcal", 0)) for m in meals)
    total_burned = sum(float(w.get("total_kcal_burned", 0)) for w in workouts)
    return {
        "days": days,
        "total_kcal_in": round(total_in, 0),
        "total_kcal_burned": round(total_burned, 0),
        "net_kcal": round(total_in - total_burned, 0),
        "avg_daily_in": round(total_in / days, 0),
        "avg_daily_burned": round(total_burned / days, 0),
        "meal_entries": len(meals),
        "workout_entries": len(workouts),
        "workout_days": len({_date_from_sk(w) for w in workouts}),
    }


def _get_metrics_snapshot(user_id: str, window_days: int = 30) -> dict[str, Any]:
    """Bundled snapshot: weight trend, calorie balance, workout consistency, streaks."""
    window_days = max(1, int(window_days))
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=window_days - 1)

    balance = _calorie_balance(user_id, start.isoformat(), today.isoformat(), window_days)
    weight = _get_weight_trend(user_id, days=window_days)
    streaks = _get_streak_data(user_id)

    weeks = max(1, round(window_days / 7, 1))
    workouts_per_week = round(balance["workout_days"] / weeks, 1)

    return {
        "window_days": window_days,
        "start_date": start.isoformat(),
        "end_date": today.isoformat(),
        "weight": weight,
        "calorie_balance": balance,
        "workout_consistency": {
            "workout_days": balance["workout_days"],
            "workouts_per_week": workouts_per_week,
        },
        "streaks": streaks,
    }


@tool("get_metrics_snapshot")
def get_metrics_snapshot(user_id: str, window_days: int = 30) -> dict[str, Any]:
    """Bundled progress snapshot over the last N days: weight trend, calorie balance, workout consistency, and streaks."""
    return _get_metrics_snapshot(user_id, window_days)
