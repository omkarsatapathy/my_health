import json
from typing import Any

import anthropic
from crewai.tools import tool

from app.config import prompt_templates, settings
from app.core.db import get_item, put_item

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
_CLASSIFY_PROMPT: str = prompt_templates["classify_intent"]

INTENT_LABELS = (
    "log_food", "log_workout", "weight_entry", "ask_advice",
    "consult_symptom", "view_dashboard", "motivation_query", "body_scan",
)


def _classify_intent(message: str, has_image: bool = False) -> dict[str, Any]:
    """LLM classifies user message into one of the intent enum labels."""
    prompt = _CLASSIFY_PROMPT.format(message=message, has_image=has_image)
    response = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=64,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw)
    # safety: normalise to known label
    if result.get("intent") not in INTENT_LABELS:
        result["intent"] = "ask_advice"
    return result


def _load_user_context(user_id: str) -> dict[str, Any]:
    """Read LT memory facts stored in MEMORY#lt for the user."""
    record = get_item(user_id, "MEMORY#lt") or {}
    return {
        "user_id": user_id,
        "weight_kg": record.get("weight_kg"),
        "calorie_baseline": record.get("calorie_baseline"),
        "gym_schedule": record.get("gym_schedule"),
        "dietary_prefs": record.get("dietary_prefs", []),
        "motivator_persona": record.get("motivator_persona", "supportive_coach"),
        "goals": record.get("goals", []),
    }


def _write_lt_memory(user_id: str, key_facts: dict[str, Any]) -> dict[str, Any]:
    """Merge key facts into MEMORY#lt — persists user context across sessions."""
    existing = get_item(user_id, "MEMORY#lt") or {}
    existing.update(key_facts)
    put_item(user_id=user_id, sk="MEMORY#lt", data=existing)
    return {"status": "saved", "keys_updated": list(key_facts.keys())}


@tool("classify_intent")
def classify_intent(message: str, has_image: bool = False) -> dict[str, Any]:
    """Classify user message into a health intent label with confidence score."""
    return _classify_intent(message, has_image)


@tool("load_user_context")
def load_user_context(user_id: str) -> dict[str, Any]:
    """Load long-term memory context for the user: weight, goals, prefs, persona."""
    return _load_user_context(user_id)


@tool("write_lt_memory")
def write_lt_memory(user_id: str, key_facts: dict[str, Any]) -> dict[str, Any]:
    """Persist key facts from this turn into long-term memory for future sessions."""
    return _write_lt_memory(user_id, key_facts)
