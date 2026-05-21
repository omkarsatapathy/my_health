from datetime import datetime, timezone
from typing import Any

from app.observability import traced_tool as tool

from app.core.db import put_item


_GOAL_SK = "INTAKE#goal"
_ALLOWED_TYPES = {"lose", "gain", "maintain", "recomp"}


def _set_goal(
    user_id: str,
    goal_type: str,
    target_kg: float | None = None,
    deadline_iso: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Persist a structured goal record at INTAKE#goal."""
    goal_type = (goal_type or "").lower().strip()
    if goal_type not in _ALLOWED_TYPES:
        return {"error": f"goal_type must be one of {sorted(_ALLOWED_TYPES)}"}

    record: dict[str, Any] = {
        "goal_type": goal_type,
        "set_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if target_kg is not None:
        record["target_kg"] = str(target_kg)
    if deadline_iso:
        record["deadline_iso"] = deadline_iso
    if notes:
        record["notes"] = notes[:300]

    put_item(user_id=user_id, sk=_GOAL_SK, data=record)
    return {"status": "saved", **record}


@tool("set_goal")
def set_goal(
    user_id: str,
    goal_type: str,
    target_kg: float | None = None,
    deadline_iso: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Save the user's health goal. goal_type is one of lose|gain|maintain|recomp. deadline_iso is YYYY-MM-DD."""
    return _set_goal(user_id, goal_type, target_kg, deadline_iso, notes)
