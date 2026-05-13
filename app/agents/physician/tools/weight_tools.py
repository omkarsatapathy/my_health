from datetime import datetime, timedelta, timezone
from typing import Any

from crewai.tools import tool

from app.agents.physician.tools.health_tools import _calculate_bmi
from app.core.db import get_item, put_item, query_sk_prefix


_BEST_PRACTICE_MSG = (
    "Before I log this, a quick reminder for accuracy:\n"
    "1. Weigh yourself in the morning, after the bathroom, before eating or drinking.\n"
    "2. Use the same scale on the same flat surface every time.\n"
    "3. Wear minimal clothing or the same outfit each weigh-in.\n"
    "4. Daily fluctuations are mostly water — weekly is enough.\n"
    "5. Track the trend, not the single number.\n"
    "Reply 'confirm' to log this weight."
)


def _log_weight_entry(user_id: str, weight_kg: float, confirmed: bool) -> dict[str, Any]:
    """Two-phase weight logging: best-practice message first, then write on confirm."""
    if not confirmed:
        return {
            "status": "pending_confirmation",
            "weight_kg": weight_kg,
            "best_practice_msg": _BEST_PRACTICE_MSG,
        }

    profile = get_item(user_id, "PROFILE#meta") or {}
    height_cm = float(profile.get("height_cm", 0) or 0)

    bmi = None
    bmi_cat = None
    if height_cm > 0:
        bmi_result = _calculate_bmi(weight_kg, height_cm)
        bmi = bmi_result.get("bmi")
        bmi_cat = bmi_result.get("bmi_category")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    put_item(
        user_id=user_id,
        sk=f"WEIGHT#{ts}",
        data={
            "weight_kg": str(weight_kg),
            "bmi": str(bmi) if bmi is not None else None,
            "bmi_category": bmi_cat,
            "confirmed": True,
            "logged_at": ts,
        },
    )

    goal = get_item(user_id, "INTAKE#goal") or {}
    target_kg = float(goal.get("target_kg") or 0)
    goal_type = (goal.get("goal_type") or "").lower()
    if target_kg > 0 and (
        (goal_type == "lose" and weight_kg <= target_kg)
        or (goal_type == "gain" and weight_kg >= target_kg)
    ):
        put_item(
            user_id=user_id,
            sk="LIFESTYLE#replan_needed",
            data={"reason": "target_reached", "flagged_at": ts, "at_weight_kg": str(weight_kg)},
        )

    return {
        "status": "logged",
        "weight_kg": weight_kg,
        "bmi": bmi,
        "bmi_category": bmi_cat,
        "logged_at": ts,
    }


def _get_weight_trend(user_id: str, days: int = 30) -> dict[str, Any]:
    """Compute weight trend over last N days: delta, rate/week, direction."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)

    all_entries = query_sk_prefix(user_id, "WEIGHT#")
    entries = sorted(
        (e for e in all_entries
         if start.isoformat() <= e.get("sk", "").split("#", 1)[-1][:10] <= today.isoformat()),
        key=lambda e: e["sk"],
    )

    if not entries:
        return {"days_queried": days, "entry_count": 0, "trend": "no_data"}

    series = [
        {
            "date": e["sk"].split("#", 1)[-1][:10],
            "weight_kg": float(e.get("weight_kg", 0)),
        }
        for e in entries
    ]

    first_kg = series[0]["weight_kg"]
    last_kg = series[-1]["weight_kg"]
    delta = round(last_kg - first_kg, 2)

    span_days = max(1, (today - datetime.fromisoformat(series[0]["date"]).date()).days)
    rate_per_week = round((delta / span_days) * 7, 2)

    if abs(delta) < 0.3:
        direction = "stable"
    elif delta < 0:
        direction = "losing"
    else:
        direction = "gaining"

    return {
        "days_queried": days,
        "entry_count": len(series),
        "first_weight_kg": first_kg,
        "last_weight_kg": last_kg,
        "delta_kg": delta,
        "rate_kg_per_week": rate_per_week,
        "direction": direction,
        "series": series,
    }


@tool("log_weight_entry")
def log_weight_entry(user_id: str, weight_kg: float, confirmed: bool = False) -> dict[str, Any]:
    """Log a weight reading. First call with confirmed=False returns best-practice message; call again with confirmed=True to write."""
    return _log_weight_entry(user_id, weight_kg, confirmed)


@tool("get_weight_trend")
def get_weight_trend(user_id: str, days: int = 30) -> dict[str, Any]:
    """Return weight time-series with delta, weekly rate, and direction over the last N days."""
    return _get_weight_trend(user_id, days)
