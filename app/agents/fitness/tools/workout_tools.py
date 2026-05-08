from datetime import datetime, timedelta, timezone
from typing import Any

from crewai.tools import tool

from app.core.db import put_item, query_sk_prefix


def _serialize_exercises(exercises: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stringify numeric fields so DynamoDB doesn't choke on floats."""
    out = []
    for ex in exercises:
        clean = {
            "type": ex.get("type"),
            "machine": ex.get("machine"),
            "duration_min": str(ex.get("duration_min", 0)),
            "settings": {k: str(v) for k, v in (ex.get("settings") or {}).items()},
            "est_kcal_burned": str(ex.get("est_kcal_burned", 0)),
        }
        out.append(clean)
    return out


def _log_workout_session(
    user_id: str,
    exercises: list[dict[str, Any]],
    total_kcal_burned: float,
    session_intensity: str,
    source: str = "text",
) -> dict[str, Any]:
    """Write WORKOUT#<ts> record; return confirmation + today's running burn total."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_prefix = ts[:10]

    put_item(
        user_id=user_id,
        sk=f"WORKOUT#{ts}",
        data={
            "exercises": _serialize_exercises(exercises),
            "total_kcal_burned": str(total_kcal_burned),
            "session_intensity": session_intensity,
            "image_count": len([e for e in exercises if e.get("from_image")]),
            "source": source,
            "logged_at": ts,
        },
    )

    daily_sessions = query_sk_prefix(user_id, f"WORKOUT#{date_prefix}")
    daily_total = sum(float(s.get("total_kcal_burned", 0)) for s in daily_sessions)

    return {
        "status": "logged",
        "exercises_count": len(exercises),
        "total_kcal_burned": round(total_kcal_burned, 1),
        "daily_total_kcal_burned": round(daily_total, 1),
        "session_intensity": session_intensity,
        "logged_at": ts,
    }


def _get_workout_history(user_id: str, last_n_days: int = 7) -> dict[str, Any]:
    """Fetch workouts in the last N days; aggregate counts and rest-day stats."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=last_n_days - 1)

    all_sessions = query_sk_prefix(user_id, "WORKOUT#")
    sessions = [
        s for s in all_sessions
        if start.isoformat() <= s.get("sk", "").split("#", 1)[-1][:10] <= today.isoformat()
    ]

    dates_with_workout = {s["sk"].split("#", 1)[-1][:10] for s in sessions}

    session_list = [
        {
            "logged_at": s.get("logged_at"),
            "exercises": s.get("exercises", []),
            "total_kcal_burned": float(s.get("total_kcal_burned", 0)),
            "session_intensity": s.get("session_intensity"),
        }
        for s in sessions
    ]

    return {
        "days_queried": last_n_days,
        "session_count": len(session_list),
        "total_kcal_burned": round(sum(s["total_kcal_burned"] for s in session_list), 1),
        "days_with_workout": len(dates_with_workout),
        "days_rested": last_n_days - len(dates_with_workout),
        "sessions": session_list,
    }


@tool("log_workout_session")
def log_workout_session(
    user_id: str,
    exercises: list[dict[str, Any]],
    total_kcal_burned: float,
    session_intensity: str,
    source: str = "text",
) -> dict[str, Any]:
    """Log a workout session to DynamoDB; returns confirmation and daily burn total."""
    return _log_workout_session(user_id, exercises, total_kcal_burned, session_intensity, source)


@tool("get_workout_history")
def get_workout_history(user_id: str, last_n_days: int = 7) -> dict[str, Any]:
    """Return workout sessions in the last N days with rest-day and burn aggregates."""
    return _get_workout_history(user_id, last_n_days)
