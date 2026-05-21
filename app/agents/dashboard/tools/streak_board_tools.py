from typing import Any

from app.observability import traced_tool as tool

from app.agents.motivation.tools.streak_tools import _get_streak_data


def _get_streak_board(user_id: str) -> dict[str, Any]:
    """All current streaks + personal bests in chart-board format."""
    streaks = _get_streak_data(user_id)
    rows = [
        {
            "category": cat,
            "current": data["current"],
            "longest": data["longest"],
            "last_updated": data.get("last_updated"),
        }
        for cat, data in streaks.items()
    ]
    return {
        "chart_type": "streak_board",
        "data": rows,
        "meta": {"categories": [r["category"] for r in rows]},
    }


@tool("get_streak_board")
def get_streak_board(user_id: str) -> dict[str, Any]:
    """All current streaks (meals, workouts, water) and personal bests."""
    return _get_streak_board(user_id)
