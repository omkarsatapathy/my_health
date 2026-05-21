from datetime import datetime, timedelta, timezone
from typing import Any

from app.observability import traced_tool as tool

from app.core.db import get_item, query_sk_prefix

_PERIODS = ("day", "week", "month")


def _date_from_sk(item: dict) -> str:
    return item.get("sk", "").split("#", 1)[-1][:10]


def _parse_anchor(anchor_date: str | None) -> datetime:
    if not anchor_date:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(anchor_date).replace(tzinfo=timezone.utc)


def _window(period: str, anchor: datetime) -> tuple[str, str, int]:
    end = anchor.date()
    if period == "day":
        return end.isoformat(), end.isoformat(), 1
    if period == "week":
        start = end - timedelta(days=6)
        return start.isoformat(), end.isoformat(), 7
    start = end - timedelta(days=29)
    return start.isoformat(), end.isoformat(), 30


def _aggregate(user_id: str, start: str, end: str) -> dict[str, Any]:
    meals = [m for m in query_sk_prefix(user_id, "MEAL#") if start <= _date_from_sk(m) <= end]
    workouts = [w for w in query_sk_prefix(user_id, "WORKOUT#") if start <= _date_from_sk(w) <= end]
    water = [w for w in query_sk_prefix(user_id, "WATER#") if start <= _date_from_sk(w) <= end]
    weights = [
        w for w in query_sk_prefix(user_id, "WEIGHT#")
        if start <= _date_from_sk(w) <= end
    ]
    weights_sorted = sorted(weights, key=lambda w: w["sk"])

    kcal_in = sum(float(m.get("total_kcal", 0)) for m in meals)
    kcal_burned = sum(float(w.get("total_kcal_burned", 0)) for w in workouts)
    glasses = sum(int(w.get("glasses", 0)) for w in water)

    weight_change = None
    if len(weights_sorted) >= 2:
        weight_change = round(
            float(weights_sorted[-1].get("weight_kg", 0))
            - float(weights_sorted[0].get("weight_kg", 0)),
            2,
        )

    return {
        "kcal_in": round(kcal_in, 0),
        "kcal_burned": round(kcal_burned, 0),
        "net_kcal": round(kcal_in - kcal_burned, 0),
        "meal_count": len(meals),
        "workout_count": len(workouts),
        "workout_days": len({_date_from_sk(w) for w in workouts}),
        "water_glasses": glasses,
        "weight_change_kg": weight_change,
    }


def _get_period_summary(user_id: str, period: str, anchor_date: str | None = None) -> dict[str, Any]:
    """Aggregate meals/workouts/water/weight for a day/week/month into a card payload."""
    if period not in _PERIODS:
        return {"error": f"period must be one of {_PERIODS}"}

    anchor = _parse_anchor(anchor_date)
    start, end, days = _window(period, anchor)
    agg = _aggregate(user_id, start, end)

    return {
        "chart_type": "summary_card",
        "data": agg,
        "meta": {"period": period, "start_date": start, "end_date": end, "days": days},
    }


@tool("get_period_summary")
def get_period_summary(user_id: str, period: str, anchor_date: str | None = None) -> dict[str, Any]:
    """Day/week/month summary card. period: day|week|month. anchor_date: YYYY-MM-DD or omit for today."""
    return _get_period_summary(user_id, period, anchor_date)
