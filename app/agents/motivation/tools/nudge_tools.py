from datetime import datetime, timedelta, timezone
from typing import Any

from crewai.tools import tool

from app.core.db import get_item, put_item, query_sk_prefix


_WEEKLY_CHALLENGES = (
    "Walk at least 6,000 steps every day this week.",
    "Hit 8 glasses of water daily for 7 straight days.",
    "Log every meal for 7 days — no skipped entries.",
    "Add one home-cooked dinner each weekday — no ordering in.",
    "20 minutes of movement daily, even on rest days (walk counts).",
    "Cut sugary drinks for 7 days — water, chai (no sugar), or black coffee only.",
    "Sleep by 11 pm on at least 5 nights this week.",
    "Take the stairs every time this week — no elevators below 5 floors.",
)

_INACTIVITY_ESCALATION = (
    (5, "physician_alert"),
    (3, "firm"),
    (2, "gentle"),
)


def _date(offset_days: int = 0) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=offset_days)).isoformat()


def _get_activity_summary(user_id: str) -> dict[str, Any]:
    """Cross-record summary: yesterday's deficit + inactivity streak + burn target."""
    yesterday = _date(1)

    meals = query_sk_prefix(user_id, f"MEAL#{yesterday}")
    kcal_in = round(sum(float(m.get("total_kcal", 0)) for m in meals), 1)

    yday_workouts = query_sk_prefix(user_id, f"WORKOUT#{yesterday}")
    kcal_burned = round(sum(float(w.get("est_kcal_burned", 0)) for w in yday_workouts), 1)

    all_workouts = query_sk_prefix(user_id, "WORKOUT#")
    workout_dates = {w.get("sk", "").split("#", 1)[-1][:10] for w in all_workouts}

    today = datetime.now(timezone.utc).date()
    inactivity_days = 0
    for offset in range(1, 31):
        d = (today - timedelta(days=offset)).isoformat()
        if d in workout_dates:
            break
        inactivity_days += 1

    escalation = "none"
    for threshold, level in _INACTIVITY_ESCALATION:
        if inactivity_days >= threshold:
            escalation = level
            break

    return {
        "yesterday_date": yesterday,
        "yesterday_kcal_in": kcal_in,
        "yesterday_kcal_burned": kcal_burned,
        "surplus_kcal": round(kcal_in - kcal_burned, 1),
        "burn_target_today": round(0.80 * kcal_in, 1),
        "inactivity_days": inactivity_days,
        "escalation_level": escalation,
    }


def _schedule_push_notification(
    user_id: str, fire_at_iso: str, message: str, notification_type: str
) -> dict[str, Any]:
    """Queue a push notification for EventBridge Lambda to deliver."""
    sk = f"PUSH_SCHEDULE#{fire_at_iso}"
    put_item(
        user_id=user_id,
        sk=sk,
        data={
            "fire_at": fire_at_iso,
            "message": message,
            "type": notification_type,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    return {"status": "scheduled", "schedule_id": sk, "fire_at": fire_at_iso}


def _get_weekly_challenge(user_id: str) -> dict[str, Any]:
    """Return active 7-day challenge; rotate weekly from static pool when expired."""
    today = datetime.now(timezone.utc).date()
    iso_year, iso_week, _ = today.isocalendar()
    week_key = f"{iso_year}-W{iso_week:02d}"

    existing = get_item(user_id, "CHALLENGE#current") or {}
    if existing.get("week_key") == week_key:
        return {
            "challenge": existing.get("challenge"),
            "week_key": week_key,
            "started_on": existing.get("started_on"),
            "status": "active",
        }

    challenge = _WEEKLY_CHALLENGES[iso_week % len(_WEEKLY_CHALLENGES)]
    started_on = today.isoformat()
    put_item(
        user_id=user_id,
        sk="CHALLENGE#current",
        data={
            "challenge": challenge,
            "week_key": week_key,
            "started_on": started_on,
        },
    )
    return {
        "challenge": challenge,
        "week_key": week_key,
        "started_on": started_on,
        "status": "new",
    }


@tool("get_activity_summary")
def get_activity_summary(user_id: str) -> dict[str, Any]:
    """Yesterday's kcal in/burned, surplus, today's 80% burn target, inactivity days + escalation."""
    return _get_activity_summary(user_id)


@tool("schedule_push_notification")
def schedule_push_notification(
    user_id: str, fire_at_iso: str, message: str, notification_type: str = "nudge"
) -> dict[str, Any]:
    """Queue a push notification (PUSH_SCHEDULE#<ts>) for delivery by EventBridge Lambda."""
    return _schedule_push_notification(user_id, fire_at_iso, message, notification_type)


@tool("get_weekly_challenge")
def get_weekly_challenge(user_id: str) -> dict[str, Any]:
    """Return this week's active challenge; rotates from a static pool each ISO week."""
    return _get_weekly_challenge(user_id)
