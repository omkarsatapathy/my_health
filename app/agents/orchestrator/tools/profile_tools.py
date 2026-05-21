from typing import Any

from app.observability import traced_tool as tool

from app.core.db import get_item, put_item, update_item


def _get_user_profile(user_id: str) -> dict[str, Any]:
    """Read PROFILE#meta: height, age, gender, calorie_target, gym_access, dietary_prefs."""
    profile = get_item(user_id, "PROFILE#meta") or {}
    return {
        "user_id": user_id,
        "height_cm": profile.get("height_cm"),
        "age": profile.get("age"),
        "gender": profile.get("gender"),
        "weight_kg": profile.get("weight_kg"),
        "calorie_target": profile.get("calorie_target", 2000),
        "gym_access": profile.get("gym_access", False),
        "dietary_prefs": profile.get("dietary_prefs", []),
        "motivator_persona": profile.get("motivator_persona", "supportive_coach"),
        "diet_schedule": profile.get("diet_schedule", {}),
    }


def _update_user_profile(user_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Partial update of PROFILE#meta with supplied fields; upserts if missing."""
    existing = get_item(user_id, "PROFILE#meta")
    if existing is None:
        put_item(user_id=user_id, sk="PROFILE#meta", data=fields)
        return {"status": "created", "profile": fields}

    updated = update_item(user_id=user_id, sk="PROFILE#meta", fields=fields)
    return {"status": "updated", "profile": updated}


@tool("get_user_profile")
def get_user_profile(user_id: str) -> dict[str, Any]:
    """Fetch full user profile from PROFILE#meta including goals and preferences."""
    return _get_user_profile(user_id)


@tool("update_user_profile")
def update_user_profile(user_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Update specific fields in the user's PROFILE#meta record."""
    return _update_user_profile(user_id, fields)
