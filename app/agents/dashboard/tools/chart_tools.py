from datetime import datetime, timedelta, timezone
from typing import Any

from crewai.tools import tool

from app.core.db import query_sk_prefix

_METRICS = ("calorie_balance", "body_weight", "water", "workout_heatmap")
_INTENSITY_RANK = {"rest": 0, "light": 1, "moderate": 2, "heavy": 3}


def _date_from_sk(item: dict) -> str:
    return item.get("sk", "").split("#", 1)[-1][:10]


def _parse_range(date_range: str | None, default_days: int = 30) -> tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    if not date_range:
        return (today - timedelta(days=default_days - 1)).isoformat(), today.isoformat()
    if ":" in date_range:
        a, b = date_range.split(":", 1)
        return a.strip(), b.strip()
    return (today - timedelta(days=default_days - 1)).isoformat(), today.isoformat()


def _daily_dates(start: str, end: str) -> list[str]:
    s = datetime.fromisoformat(start).date()
    e = datetime.fromisoformat(end).date()
    out = []
    d = s
    while d <= e:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _calorie_balance_series(user_id: str, start: str, end: str) -> list[dict]:
    meals = [m for m in query_sk_prefix(user_id, "MEAL#") if start <= _date_from_sk(m) <= end]
    workouts = [w for w in query_sk_prefix(user_id, "WORKOUT#") if start <= _date_from_sk(w) <= end]
    by_date: dict[str, dict[str, float]] = {d: {"kcal_in": 0.0, "kcal_burned": 0.0} for d in _daily_dates(start, end)}
    for m in meals:
        by_date.setdefault(_date_from_sk(m), {"kcal_in": 0.0, "kcal_burned": 0.0})["kcal_in"] += float(m.get("total_kcal", 0))
    for w in workouts:
        by_date.setdefault(_date_from_sk(w), {"kcal_in": 0.0, "kcal_burned": 0.0})["kcal_burned"] += float(w.get("total_kcal_burned", 0))
    return [
        {"date": d, "kcal_in": round(v["kcal_in"], 0), "kcal_burned": round(v["kcal_burned"], 0), "net": round(v["kcal_in"] - v["kcal_burned"], 0)}
        for d, v in sorted(by_date.items())
    ]


def _body_weight_series(user_id: str, start: str, end: str) -> list[dict]:
    entries = sorted(
        (e for e in query_sk_prefix(user_id, "WEIGHT#") if start <= _date_from_sk(e) <= end),
        key=lambda e: e["sk"],
    )
    return [{"date": _date_from_sk(e), "weight_kg": float(e.get("weight_kg", 0))} for e in entries]


def _water_series(user_id: str, start: str, end: str, target: int = 8) -> list[dict]:
    water = [w for w in query_sk_prefix(user_id, "WATER#") if start <= _date_from_sk(w) <= end]
    by_date: dict[str, int] = {d: 0 for d in _daily_dates(start, end)}
    for w in water:
        by_date[_date_from_sk(w)] = by_date.get(_date_from_sk(w), 0) + int(w.get("glasses", 0))
    return [{"date": d, "glasses": g, "target": target} for d, g in sorted(by_date.items())]


def _workout_heatmap(user_id: str, start: str, end: str) -> list[dict]:
    workouts = [w for w in query_sk_prefix(user_id, "WORKOUT#") if start <= _date_from_sk(w) <= end]
    by_date: dict[str, str] = {d: "rest" for d in _daily_dates(start, end)}
    for w in workouts:
        d = _date_from_sk(w)
        intensity = (w.get("session_intensity") or "light").lower()
        if _INTENSITY_RANK.get(intensity, 0) > _INTENSITY_RANK.get(by_date.get(d, "rest"), 0):
            by_date[d] = intensity
    return [{"date": d, "intensity": i} for d, i in sorted(by_date.items())]


def _get_chart_series(user_id: str, metric: str, date_range: str | None = None) -> dict[str, Any]:
    """Time-series chart data; metric: calorie_balance|body_weight|water|workout_heatmap."""
    if metric not in _METRICS:
        return {"error": f"metric must be one of {_METRICS}"}

    default_days = 30 if metric != "workout_heatmap" else 30
    start, end = _parse_range(date_range, default_days)

    if metric == "calorie_balance":
        data = _calorie_balance_series(user_id, start, end)
        chart_type = "bar"
    elif metric == "body_weight":
        data = _body_weight_series(user_id, start, end)
        chart_type = "line"
    elif metric == "water":
        data = _water_series(user_id, start, end)
        chart_type = "bar"
    else:
        data = _workout_heatmap(user_id, start, end)
        chart_type = "heatmap"

    return {
        "chart_type": chart_type,
        "data": data,
        "meta": {"metric": metric, "start_date": start, "end_date": end},
    }


@tool("get_chart_series")
def get_chart_series(user_id: str, metric: str, date_range: str | None = None) -> dict[str, Any]:
    """Chart-ready series. metric: calorie_balance|body_weight|water|workout_heatmap. date_range: 'YYYY-MM-DD:YYYY-MM-DD' or omit for last 30 days."""
    return _get_chart_series(user_id, metric, date_range)
