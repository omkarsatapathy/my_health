from datetime import datetime, timedelta, timezone
from typing import Any

from crewai.tools import tool

from app.core.db import get_item, query_sk_prefix


def _bmi_category(bmi: float) -> str:
    if bmi < 18.5:
        return "underweight"
    if bmi < 25.0:
        return "normal"
    if bmi < 30.0:
        return "overweight"
    return "obese"


def _calculate_bmi(weight_kg: float, height_cm: float) -> dict[str, Any]:
    """Standard BMI = weight_kg / height_m^2, with WHO category label."""
    if weight_kg <= 0 or height_cm <= 0:
        return {"error": "weight_kg and height_cm must be positive"}
    height_m = height_cm / 100.0
    bmi = round(weight_kg / (height_m * height_m), 1)
    return {
        "weight_kg": weight_kg,
        "height_cm": height_cm,
        "bmi": bmi,
        "bmi_category": _bmi_category(bmi),
    }


def _date_from_sk(item: dict) -> str:
    return item.get("sk", "").split("#", 1)[-1][:10]


def _assess_sedentary_risk(user_id: str) -> dict[str, Any]:
    """Last 3 days: high kcal_in + zero workouts -> escalate risk_level."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=2)

    profile = get_item(user_id, "PROFILE#meta") or {}
    calorie_target = float(profile.get("calorie_target", 2000) or 2000)

    meals = [
        m for m in query_sk_prefix(user_id, "MEAL#")
        if start.isoformat() <= _date_from_sk(m) <= today.isoformat()
    ]
    workouts = [
        w for w in query_sk_prefix(user_id, "WORKOUT#")
        if start.isoformat() <= _date_from_sk(w) <= today.isoformat()
    ]

    total_kcal_in = sum(float(m.get("total_kcal", 0)) for m in meals)
    avg_daily_kcal = total_kcal_in / 3
    high_intake = avg_daily_kcal > calorie_target * 1.05

    days_with_workout = len({_date_from_sk(w) for w in workouts})
    workout_count = len(workouts)

    if workout_count == 0 and high_intake:
        risk_level = "high"
        action = "Schedule a workout today; intake is high and activity is zero across 3 days."
    elif days_with_workout <= 1 and high_intake:
        risk_level = "moderate"
        action = "Add a 20-min walk or light home routine today."
    elif days_with_workout == 0:
        risk_level = "moderate"
        action = "No workouts in 3 days — a brisk 20-min walk would help."
    else:
        risk_level = "low"
        action = "Activity level is reasonable — keep it consistent."

    return {
        "window_days": 3,
        "avg_daily_kcal_in": round(avg_daily_kcal, 0),
        "calorie_target": calorie_target,
        "workout_count": workout_count,
        "days_with_workout": days_with_workout,
        "high_intake": high_intake,
        "risk_level": risk_level,
        "recommended_action": action,
    }


def _month_bounds(month: str | None) -> tuple:
    today = datetime.now(timezone.utc).date()
    if month:
        year, mo = month.split("-")
        first = datetime(int(year), int(mo), 1, tzinfo=timezone.utc).date()
    else:
        first = today.replace(day=1)
    if first.month == 12:
        last = first.replace(year=first.year + 1, month=1) - timedelta(days=1)
    else:
        last = first.replace(month=first.month + 1) - timedelta(days=1)
    return first, min(last, today)


def _generate_health_report(user_id: str, month: str | None = None) -> dict[str, Any]:
    """Monthly: weight delta, avg kcal in/out, gym %, hydration, raw inputs for summary."""
    first, end = _month_bounds(month)
    days_in_window = (end - first).days + 1

    def in_range(item: dict) -> bool:
        return first.isoformat() <= _date_from_sk(item) <= end.isoformat()

    meals = [m for m in query_sk_prefix(user_id, "MEAL#") if in_range(m)]
    workouts = [w for w in query_sk_prefix(user_id, "WORKOUT#") if in_range(w)]
    waters = [w for w in query_sk_prefix(user_id, "WATER#") if in_range(w)]
    weights = sorted(
        (w for w in query_sk_prefix(user_id, "WEIGHT#") if in_range(w)),
        key=lambda x: x["sk"],
    )

    total_kcal_in = sum(float(m.get("total_kcal", 0)) for m in meals)
    total_kcal_burned = sum(float(w.get("total_kcal_burned", 0)) for w in workouts)
    avg_kcal_in = round(total_kcal_in / days_in_window, 0)
    avg_kcal_burned = round(total_kcal_burned / days_in_window, 0)

    workout_days = len({_date_from_sk(w) for w in workouts})
    gym_consistency_pct = round((workout_days / days_in_window) * 100, 1)

    total_glasses = sum(float(w.get("glasses", 0)) for w in waters)
    hydration_score_pct = round((total_glasses / (8 * days_in_window)) * 100, 1)

    weight_delta_kg = None
    if len(weights) >= 2:
        weight_delta_kg = round(
            float(weights[-1].get("weight_kg", 0)) - float(weights[0].get("weight_kg", 0)),
            2,
        )

    return {
        "month": f"{first.year}-{first.month:02d}",
        "days_in_window": days_in_window,
        "weight_delta_kg": weight_delta_kg,
        "weight_entry_count": len(weights),
        "avg_kcal_in": avg_kcal_in,
        "avg_kcal_burned": avg_kcal_burned,
        "workout_days": workout_days,
        "gym_consistency_pct": gym_consistency_pct,
        "hydration_score_pct": hydration_score_pct,
    }


@tool("calculate_bmi")
def calculate_bmi(weight_kg: float, height_cm: float) -> dict[str, Any]:
    """Standard BMI calculation with WHO category label."""
    return _calculate_bmi(weight_kg, height_cm)


@tool("assess_sedentary_risk")
def assess_sedentary_risk(user_id: str) -> dict[str, Any]:
    """Cross-references last 3 days of meals + workouts; returns risk level and action."""
    return _assess_sedentary_risk(user_id)


@tool("generate_health_report")
def generate_health_report(user_id: str, month: str | None = None) -> dict[str, Any]:
    """Monthly aggregate: weight delta, avg kcal in/out, gym consistency, hydration."""
    return _generate_health_report(user_id, month)
