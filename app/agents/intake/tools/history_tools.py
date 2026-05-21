from datetime import datetime, timezone
from typing import Any

from app.observability import traced_tool as tool

from app.core.db import get_item, put_item


_HISTORY_SK = "INTAKE#history"
_LIST_FIELDS = ("conditions", "allergies", "medications", "surgeries")


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _merge_history(existing: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Merge list fields by union; replace removals when key '<field>_remove' is sent."""
    merged = dict(existing)
    for field in _LIST_FIELDS:
        current = set(_normalize_list(existing.get(field)))
        add = set(_normalize_list(updates.get(field)))
        remove = set(_normalize_list(updates.get(f"{field}_remove")))
        merged[field] = sorted((current | add) - remove)
    if "notes" in updates and updates["notes"]:
        merged["notes"] = str(updates["notes"])[:500]
    return merged


def _upsert_health_history(user_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Merge new conditions/allergies/medications/surgeries into INTAKE#history."""
    existing = get_item(user_id, _HISTORY_SK) or {}
    merged = _merge_history(existing, fields)
    merged["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    put_item(user_id=user_id, sk=_HISTORY_SK, data=merged)
    return {
        "status": "updated",
        "conditions": merged.get("conditions", []),
        "allergies": merged.get("allergies", []),
        "medications": merged.get("medications", []),
        "surgeries": merged.get("surgeries", []),
        "notes": merged.get("notes"),
    }


@tool("upsert_health_history")
def upsert_health_history(user_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Merge conditions, allergies, medications, surgeries into the user's INTAKE#history. Use '<field>_remove' lists to delete entries."""
    return _upsert_health_history(user_id, fields)
