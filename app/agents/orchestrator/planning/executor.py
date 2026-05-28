"""Decides fast path vs planner path, and runs the planner path end-to-end."""
import asyncio
from functools import partial
from typing import Optional

from app.agents.orchestrator.planning.dispatcher import execute_plan
from app.agents.orchestrator.planning.planner import build_plan
from app.agents.orchestrator.planning.synthesizer import synthesize
from app.config import planning_config
from app.observability import get_logger

log = get_logger("orchestrator.executor")

_FAST_THRESHOLD = planning_config.get("fast_path_confidence_threshold", 0.85)
_ALWAYS_PLAN = bool(planning_config.get("always_plan", True))
_COMPOUND_MARKERS = (" also ", " plus ", "; ", "additionally", " then ", " as well")
# Intents that map cleanly to a single specialist — never need the multi-agent planner.
_SINGLE_DOMAIN_INTENTS = frozenset({
    "log_food", "log_workout", "weight_entry", "log_water",
    "consult_symptom", "first_aid", "supplement_query",
    "intake_query", "motivation_query", "body_scan",
})
_HANDOFF_CUES = (
    "fitness agent", "nutrition agent", "physician agent", "consult agent",
    "intake agent", "progress agent", "dashboard agent", "motivation agent",
    "lifestyle agent", "next step", "ready to move", "hand off", "handing off",
    "route you to", "i'll route",
)


def should_use_planner(message: str, intent_result: dict, chat_summary: str = "") -> bool:
    """Return True if the query should go through the multi-agent planner."""
    if not planning_config.get("enabled"):
        return False
    intent = intent_result.get("intent")
    confidence = float(intent_result.get("confidence") or 0.0)
    # Single-domain high-confidence intents short-circuit to fast path regardless of other heuristics.
    if intent in _SINGLE_DOMAIN_INTENTS and confidence >= _FAST_THRESHOLD:
        return False
    if _ALWAYS_PLAN:
        return True
    if confidence < _FAST_THRESHOLD:
        return True
    msg = (message or "").lower()
    if any(m in msg for m in _COMPOUND_MARKERS):
        return True
    if msg.count("?") >= 2:
        return True
    if chat_summary and any(c in chat_summary.lower() for c in _HANDOFF_CUES):
        return True
    return False


async def run_planner_path(
    *,
    user_id: str,
    message: str,
    chat_summary: str,
    user_context: dict,
    plan_summary: str,
) -> Optional[str]:
    """Plan -> execute -> synthesize. Returns None if planning failed (caller falls back)."""
    loop = asyncio.get_running_loop()
    try:
        plan = await loop.run_in_executor(
            None,
            partial(
                build_plan,
                message=message,
                user_id=user_id,
                user_context=user_context,
                chat_summary=chat_summary,
                plan_summary=plan_summary,
            ),
        )
    except Exception:
        log.exception("planner_failed_falling_back")
        return None

    results = await execute_plan(plan, user_id)
    if not results:
        log.warning("planner_no_results")
        return None

    try:
        reply = await loop.run_in_executor(None, partial(synthesize, message, results))
    except Exception:
        log.exception("synthesizer_failed_falling_back")
        return None
    return reply
