from datetime import datetime, timezone
from typing import Any

from app.observability import traced_tool as tool

from app.core.db import get_item
from app.agents.physician.tools.weight_tools import _get_weight_trend


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_goal_progress(user_id: str) -> dict[str, Any]:
    """Join INTAKE#goal with current weight + recent trend; compute % done, eta, on-track flag."""
    goal = get_item(user_id, "INTAKE#goal")
    if not goal:
        return {"status": "no_goal", "hint": "Ask the user to set a goal via the Intake agent."}

    goal_type = goal.get("goal_type")
    target_kg = _safe_float(goal.get("target_kg"))
    deadline_iso = goal.get("deadline_iso")
    set_at = goal.get("set_at")

    trend = _get_weight_trend(user_id, days=30)
    current_kg = _safe_float(trend.get("last_weight_kg"))

    if goal_type == "maintain":
        on_track = trend.get("direction") == "stable"
        return {
            "status": "tracked",
            "goal_type": goal_type,
            "current_kg": current_kg,
            "weight_direction_30d": trend.get("direction"),
            "rate_kg_per_week": trend.get("rate_kg_per_week"),
            "on_track": on_track,
        }

    if current_kg is None or target_kg is None:
        return {
            "status": "incomplete_data",
            "goal_type": goal_type,
            "target_kg": target_kg,
            "current_kg": current_kg,
            "hint": "Need at least one logged weight to estimate progress.",
        }

    start_kg = _safe_float(trend.get("first_weight_kg")) or current_kg
    total_change_needed = target_kg - start_kg
    progress_change = current_kg - start_kg

    if total_change_needed == 0:
        pct_to_goal = 100.0
    else:
        pct_to_goal = round((progress_change / total_change_needed) * 100, 1)
        pct_to_goal = max(0.0, min(pct_to_goal, 999.0))

    remaining_kg = round(target_kg - current_kg, 2)
    rate = _safe_float(trend.get("rate_kg_per_week")) or 0.0

    eta_weeks: float | None = None
    moving_right_way = (
        (goal_type == "lose" and rate < 0)
        or (goal_type == "gain" and rate > 0)
        or (goal_type == "recomp" and rate != 0)
    )
    if moving_right_way and rate != 0:
        eta_weeks = round(remaining_kg / rate, 1)
        if eta_weeks < 0:
            eta_weeks = abs(eta_weeks)

    on_track: bool | None = None
    if deadline_iso:
        try:
            deadline = datetime.fromisoformat(deadline_iso).date()
            today = datetime.now(timezone.utc).date()
            weeks_left = max(0.0, (deadline - today).days / 7)
            if eta_weeks is not None:
                on_track = eta_weeks <= weeks_left
        except ValueError:
            pass

    return {
        "status": "tracked",
        "goal_type": goal_type,
        "target_kg": target_kg,
        "current_kg": current_kg,
        "start_kg": start_kg,
        "remaining_kg": remaining_kg,
        "pct_to_goal": pct_to_goal,
        "rate_kg_per_week": rate,
        "eta_weeks": eta_weeks,
        "deadline_iso": deadline_iso,
        "set_at": set_at,
        "on_track": on_track,
    }


@tool("get_goal_progress")
def get_goal_progress(user_id: str) -> dict[str, Any]:
    """Compute progress toward the stored goal: % done, remaining kg, eta in weeks, on-track flag vs deadline."""
    return _get_goal_progress(user_id)
