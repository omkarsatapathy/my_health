"""Anthropic-native fast path for log_food intent — one LLM call, no crewai overhead."""
from typing import Optional

import anthropic

from app.agents.nutrition.tools.meal_tools import (
    _get_daily_calorie_log, _log_meal_entry, _parse_date,
)
from app.agents.nutrition.tools.water_tools import _log_water_intake
from app.config import llm_config, settings
from app.observability import get_logger
from app.status_events import agent as status_agent
from app.status_events import tool as status_tool

log = get_logger("orchestrator.nutrition_fastpath")

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
_MODEL: str = llm_config["anthropic"]["chat_model"]

ELIGIBLE_INTENTS = frozenset({"log_food"})

_SYSTEM = (
    "You are a nutrition logger for an Indian user. Pick ONE tool that matches the message:\n"
    "- log_meal_entry: user just ate something. Estimate kcal + macros using typical Indian portions.\n"
    "- log_water_intake: user reports drinking water (1 glass = 250ml).\n"
    "- get_daily_calorie_log: user asks 'how many calories today', 'what did I eat yesterday', etc.\n"
    "\n"
    "VISION CONTEXT: if the message contains an `[Image Analysis — type: food]` block, "
    "use the values from its `Extracted data` JSON VERBATIM — do NOT re-estimate:\n"
    "  - total_kcal = structured_data.calories\n"
    "  - macros.protein_g, carbs_g, fat_g = same fields in structured_data\n"
    "  - items = structured_data.food_items\n"
    "Pick meal_type from the user's text (breakfast/lunch/dinner/snack); default to 'snack' if unclear.\n"
    "\n"
    "Always call exactly one tool. Do not reply in text."
)


# Bail signal — let caller fall back to crewai when image isn't a food image.
_NON_FOOD_IMAGE_TYPES = ("treadmill", "workout", "body_posture", "other")

_TOOLS = [
    {
        "name": "log_meal_entry",
        "description": "Log a meal the user just ate; estimates kcal+macros from item names.",
        "input_schema": {
            "type": "object",
            "properties": {
                "meal_type": {"type": "string", "enum": ["breakfast", "lunch", "dinner", "snack"]},
                "items": {"type": "array", "items": {"type": "string"}},
                "total_kcal": {"type": "number"},
                "macros": {
                    "type": "object",
                    "properties": {
                        "protein_g": {"type": "number"},
                        "carbs_g": {"type": "number"},
                        "fat_g": {"type": "number"},
                    },
                    "required": ["protein_g", "carbs_g", "fat_g"],
                },
            },
            "required": ["meal_type", "items", "total_kcal", "macros"],
        },
    },
    {
        "name": "log_water_intake",
        "description": "Log water intake in glasses (250ml each).",
        "input_schema": {
            "type": "object",
            "properties": {"glasses": {"type": "integer", "minimum": 1}},
            "required": ["glasses"],
        },
    },
    {
        "name": "get_daily_calorie_log",
        "description": "Look up meals + total kcal for a date (today / yesterday / YYYY-MM-DD).",
        "input_schema": {
            "type": "object",
            "properties": {"date": {"type": "string"}},
            "required": ["date"],
        },
    },
]


def _format_reply(name: str, result: dict) -> str:
    if name == "log_meal_entry":
        items = ", ".join(result.get("items", []) or [])
        items_line = f" — {items}" if items else ""
        return (
            f"Got it! Logged your {result['meal_type']}{items_line} at "
            f"**{result['kcal']:.0f} kcal**. That brings today's total to "
            f"**{result['daily_total_kcal']:.0f} kcal**. Keep it up!"
        )
    if name == "log_water_intake":
        glasses = result["glasses_added"]
        word = "glass" if glasses == 1 else "glasses"
        return (
            f"Nice — added {glasses} {word} of water. "
            f"You're at **{result['daily_total_glasses']} glasses** for today. "
            f"Stay hydrated!"
        )
    if name == "get_daily_calorie_log":
        if not result["meals"]:
            return (
                f"Looks like nothing's logged for **{result['date']}** yet. "
                f"Want to log something now?"
            )
        lines = [f"Here's your day at a glance for **{result['date']}** "
                 f"— **{result['total_kcal']:.0f} kcal** total:"]
        for m in result["meals"]:
            items = ", ".join(m["items"]) or "(unspecified)"
            lines.append(f"• {m['meal_type'].capitalize()}: {items} ({m['kcal']:.0f} kcal)")
        return "\n".join(lines)
    return str(result)


def can_handle(intent: str) -> bool:
    return intent in ELIGIBLE_INTENTS


def run(user_id: str, message: str) -> Optional[str]:
    """One LLM call -> dispatch tool -> templated reply. Returns None if not handleable; caller falls back."""
    log.info("nutrition_fastpath_start", extra={"msg_len": len(message)})
    # Defer to crewai when the attached image isn't food (workout/body/etc).
    if any(f"type: {t}" in message for t in _NON_FOOD_IMAGE_TYPES):
        log.info("nutrition_fastpath_skip_non_food_image")
        return None
    status_agent("Nutrition")
    resp = _client.messages.create(
        model=_MODEL,
        max_tokens=512,
        system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
        tools=_TOOLS,
        messages=[{"role": "user", "content": message}],
    )
    tool_uses = [b for b in resp.content if b.type == "tool_use"]
    if not tool_uses:
        log.info("nutrition_fastpath_no_tool_use", extra={"stop": resp.stop_reason})
        return None  # signal: caller falls back to crewai

    block = tool_uses[0]
    name, args = block.name, dict(block.input)
    status_tool(name)
    log.info("nutrition_fastpath_dispatch", extra={"tool": name})

    if name == "log_meal_entry":
        result = _log_meal_entry(
            user_id,
            args["meal_type"], args["items"],
            float(args["total_kcal"]), {k: float(v) for k, v in args["macros"].items()},
        )
        result["items"] = args["items"]  # carry through for the reply template
    elif name == "log_water_intake":
        result = _log_water_intake(user_id, int(args["glasses"]))
    elif name == "get_daily_calorie_log":
        result = _get_daily_calorie_log(user_id, _parse_date(args.get("date", "today")))
    else:
        log.warning("nutrition_fastpath_unknown_tool", extra={"name": name})
        return None  # unknown tool -> fall back

    return _format_reply(name, result)
