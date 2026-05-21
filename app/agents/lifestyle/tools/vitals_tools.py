from datetime import datetime, timezone
from typing import Any

from app.observability import traced_tool as tool

from app.core.db import put_item


def _save_vitals(
    user_id: str,
    heart_rate_bpm: int | None = None,
    cholesterol_mgdl: float | None = None,
    bp_systolic: int | None = None,
    bp_diastolic: int | None = None,
    fasting_glucose_mgdl: float | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Persist a vitals snapshot keyed by today's date."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sk = f"LIFESTYLE#vitals#{today}"
    record: dict[str, Any] = {"recorded_on": today}
    if heart_rate_bpm is not None:
        record["heart_rate_bpm"] = str(heart_rate_bpm)
    if cholesterol_mgdl is not None:
        record["cholesterol_mgdl"] = str(cholesterol_mgdl)
    if bp_systolic is not None:
        record["bp_systolic"] = str(bp_systolic)
    if bp_diastolic is not None:
        record["bp_diastolic"] = str(bp_diastolic)
    if fasting_glucose_mgdl is not None:
        record["fasting_glucose_mgdl"] = str(fasting_glucose_mgdl)
    if notes:
        record["notes"] = notes[:300]

    put_item(user_id=user_id, sk=sk, data=record)
    return {"status": "saved", "sk": sk, **record}


@tool("save_vitals")
def save_vitals(
    user_id: str,
    heart_rate_bpm: int | None = None,
    cholesterol_mgdl: float | None = None,
    bp_systolic: int | None = None,
    bp_diastolic: int | None = None,
    fasting_glucose_mgdl: float | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Save vitals snapshot (HR, cholesterol, BP, fasting glucose) at LIFESTYLE#vitals#<date>."""
    return _save_vitals(
        user_id, heart_rate_bpm, cholesterol_mgdl, bp_systolic, bp_diastolic, fasting_glucose_mgdl, notes
    )
