from datetime import datetime, timedelta, timezone
from typing import Any

from app.observability import traced_tool as tool

from app.core.db import get_item, put_item, query_sk_prefix


_MILESTONES = (7, 30, 100)
_VALID_CATEGORIES = ("meals", "workouts", "water")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _yesterday() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def _get_streak_data(user_id: str) -> dict[str, Any]:
    """Read all STREAK# records for a user."""
    items = query_sk_prefix(user_id, "STREAK#")
    streaks: dict[str, Any] = {}
    for item in items:
        category = item.get("sk", "").split("#", 1)[-1]
        streaks[category] = {
            "current": int(item.get("current", 0)),
            "longest": int(item.get("longest", 0)),
            "last_updated": item.get("last_updated"),
        }
    for cat in _VALID_CATEGORIES:
        streaks.setdefault(cat, {"current": 0, "longest": 0, "last_updated": None})
    return streaks


def _update_streak(user_id: str, category: str, success_today: bool) -> dict[str, Any]:
    """Increment, hold, or reset a category streak; flag milestones."""
    if category not in _VALID_CATEGORIES:
        return {"error": f"invalid category; expected one of {_VALID_CATEGORIES}"}

    sk = f"STREAK#{category}"
    today = _today()
    yesterday = _yesterday()
    existing = get_item(user_id, sk) or {}
    current = int(existing.get("current", 0))
    longest = int(existing.get("longest", 0))
    last_updated = existing.get("last_updated")

    if not success_today:
        new_current = 0
    elif last_updated == today:
        new_current = current
    elif last_updated == yesterday:
        new_current = current + 1
    else:
        new_current = 1

    new_longest = max(longest, new_current)
    milestone_flag = new_current in _MILESTONES and new_current > current

    put_item(
        user_id=user_id,
        sk=sk,
        data={
            "current": new_current,
            "longest": new_longest,
            "last_updated": today,
        },
    )

    return {
        "category": category,
        "current": new_current,
        "longest": new_longest,
        "milestone_flag": milestone_flag,
        "milestone_value": new_current if milestone_flag else None,
    }


@tool("get_streak_data")
def get_streak_data(user_id: str) -> dict[str, Any]:
    """Return current and longest streaks for meals, workouts, and water."""
    return _get_streak_data(user_id)


@tool("update_streak")
def update_streak(user_id: str, category: str, success_today: bool) -> dict[str, Any]:
    """Update a category streak (meals|workouts|water); returns count and milestone flag."""
    return _update_streak(user_id, category, success_today)
