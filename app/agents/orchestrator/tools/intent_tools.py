import json
from typing import Any

import anthropic
from app.observability import traced_tool as tool

from app.config import prompt_templates, settings
from app.core.db import get_item, put_item

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
_CLASSIFY_PROMPT: str = prompt_templates["classify_intent"]

INTENT_LABELS = (
    "log_food", "log_workout", "weight_entry", "ask_advice",
    "consult_symptom", "view_dashboard", "motivation_query", "body_scan",
    "intake_query", "progress_query", "lifestyle_planning",
)


def _build_classify_system() -> str:
    """Strip the dynamic Message/has_image block; keep all static rules + examples as the system prompt."""
    lines = _CLASSIFY_PROMPT.splitlines()
    return "\n".join(l for l in lines if "{message}" not in l and "{has_image}" not in l).strip()


_CLASSIFY_SYSTEM = _build_classify_system()


def _classify_intent(message: str, has_image: bool = False) -> dict[str, Any]:
    """LLM classifies user message into one of the intent enum labels."""
    user_block = f'Message: "{message}"\nHas image attached: {has_image}'
    response = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=64,
        system=[{"type": "text", "text": _CLASSIFY_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_block}],
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
    """Read LT memory facts plus the active lifestyle plan summary and re-plan flag."""
    record = get_item(user_id, "MEMORY#lt") or {}
    plan = get_item(user_id, "LIFESTYLE#plan") or {}
    replan = get_item(user_id, "LIFESTYLE#replan_needed") or {}
    replan_active = bool(replan) and replan.get("reason") and replan.get("reason") != "cleared"
    return {
        "user_id": user_id,
        "weight_kg": record.get("weight_kg"),
        "calorie_baseline": record.get("calorie_baseline"),
        "gym_schedule": record.get("gym_schedule"),
        "dietary_prefs": record.get("dietary_prefs", []),
        "motivator_persona": record.get("motivator_persona", "supportive_coach"),
        "goals": record.get("goals", []),
        "lifestyle_plan_summary": plan.get("plan_text_condensed"),
        "lifestyle_plan_version": plan.get("version"),
        "replan_needed": replan_active,
        "replan_reason": replan.get("reason") if replan_active else None,
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
