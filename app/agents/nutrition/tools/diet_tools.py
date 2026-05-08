import json
from typing import Any

import anthropic
from crewai.tools import tool

from app.config import prompt_templates, settings
from app.core.db import get_item

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
_MEAL_PLAN_PROMPT: str = prompt_templates["generate_meal_plan"]


def _get_diet_schedule(user_id: str) -> dict[str, Any]:
    """Read diet schedule and meal times from PROFILE#meta."""
    profile = get_item(user_id, "PROFILE#meta") or {}
    schedule = profile.get("diet_schedule", {})

    return {
        "meal_times": schedule.get("meal_times", {
            "breakfast": "08:00",
            "lunch": "13:00",
            "dinner": "20:00",
        }),
        "calorie_target": profile.get("calorie_target", 2000),
        "dietary_prefs": profile.get("dietary_prefs", []),
    }


def _generate_meal_plan(
    user_id: str,
    calorie_target: int,
    preferences: list[str],
    budget_level: str,
) -> dict[str, Any]:
    """Call Claude to generate a 3-meal Indian day plan within calorie target."""
    prompt = _MEAL_PLAN_PROMPT.format(
        calorie_target=calorie_target,
        preferences=", ".join(preferences) if preferences else "vegetarian, no restrictions",
        budget_level=budget_level,
    )

    response = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    return json.loads(raw)


@tool("get_diet_schedule")
def get_diet_schedule(user_id: str) -> dict[str, Any]:
    """Return configured meal times and calorie target from user profile."""
    return _get_diet_schedule(user_id)


@tool("generate_meal_plan")
def generate_meal_plan(
    user_id: str,
    calorie_target: int,
    preferences: list[str],
    budget_level: str,
) -> dict[str, Any]:
    """Generate a 3-meal Indian day plan aligned to calorie target and preferences."""
    return _generate_meal_plan(user_id, calorie_target, preferences, budget_level)
