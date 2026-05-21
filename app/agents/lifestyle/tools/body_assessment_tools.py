from datetime import datetime, timezone
from typing import Any

from app.observability import traced_tool as tool

from app.core.db import put_item


def _save_body_assessment(user_id: str, structured_text: str) -> dict[str, Any]:
    """Persist text-only body posture description. Never accepts image bytes."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sk = f"LIFESTYLE#body_assessment#{today}"
    text = (structured_text or "").strip()[:4000]
    put_item(
        user_id=user_id,
        sk=sk,
        data={"recorded_on": today, "structured_text": text},
    )
    return {"status": "saved", "sk": sk, "chars": len(text)}


@tool("save_body_assessment")
def save_body_assessment(user_id: str, structured_text: str) -> dict[str, Any]:
    """Save the text-only body posture description from the vision layer at LIFESTYLE#body_assessment#<date>. Input must already be text — no image bytes."""
    return _save_body_assessment(user_id, structured_text)
