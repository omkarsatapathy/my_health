from datetime import datetime, timezone
from typing import Any

from app.observability import traced_tool as tool

from app.core.db import get_item, put_item


_STATE_SK = "LIFESTYLE#plan_state"


def _save_plan_answer(user_id: str, field: str, value: Any) -> dict[str, Any]:
    """Merge a single interview answer into the in-progress plan state."""
    existing = get_item(user_id, _STATE_SK) or {}
    answers = dict(existing.get("answers") or {})
    answers[field] = value
    record = {
        "answers": answers,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    put_item(user_id=user_id, sk=_STATE_SK, data=record)
    return {"status": "saved", "field": field, "answered_fields": sorted(answers.keys())}


def _get_plan_state(user_id: str) -> dict[str, Any]:
    """Return current in-progress interview state for the user."""
    record = get_item(user_id, _STATE_SK) or {}
    return {
        "answers": record.get("answers") or {},
        "updated_at": record.get("updated_at"),
    }


@tool("save_plan_answer")
def save_plan_answer(user_id: str, field: str, value: Any) -> dict[str, Any]:
    """Save one interview answer (motivation, goal, transformation_focus, medical, weight, target, vitals, body_photo_consent) into LIFESTYLE#plan_state."""
    return _save_plan_answer(user_id, field, value)


@tool("get_plan_state")
def get_plan_state(user_id: str) -> dict[str, Any]:
    """Return the in-progress interview answers so the agent can decide what to ask next."""
    return _get_plan_state(user_id)
