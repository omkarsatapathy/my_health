from datetime import datetime, timezone
from typing import Any

from app.observability import traced_tool as tool

from app.core.db import put_item, query_sk_prefix


def _log_water_intake(user_id: str, glasses: int) -> dict[str, Any]:
    """Write WATER#<ts> to DynamoDB; return confirmation and daily total glasses."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_prefix = ts[:10]

    put_item(
        user_id=user_id,
        sk=f"WATER#{ts}",
        data={"glasses": glasses, "logged_at": ts},
    )

    daily_records = query_sk_prefix(user_id, f"WATER#{date_prefix}")
    daily_total = sum(int(r.get("glasses", 0)) for r in daily_records)

    return {
        "status": "logged",
        "glasses_added": glasses,
        "daily_total_glasses": daily_total,
        "logged_at": ts,
    }


@tool("log_water_intake")
def log_water_intake(user_id: str, glasses: int) -> dict[str, Any]:
    """Log water intake in glasses; returns daily running total."""
    return _log_water_intake(user_id, glasses)
