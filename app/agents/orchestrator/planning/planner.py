"""LLM planner that turns a user message into a validated Plan DAG."""
import json
import re

import anthropic
from pydantic import ValidationError

from app.agents.orchestrator.planning.registry import CAPABILITIES
from app.agents.orchestrator.planning.schemas import Plan
from app.config import llm_config, planning_config, prompt_templates, settings
from app.observability import get_logger

log = get_logger("orchestrator.planner")

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
_PROMPT: str = prompt_templates["planner_prompt"]
_MODEL: str = llm_config["anthropic"].get("planner_model") or llm_config["anthropic"]["chat_model"]
_MAX_STEPS: int = planning_config.get("max_steps", 6)


def _agent_catalog() -> str:
    return "\n".join(f"- {name}: {desc}" for name, desc in CAPABILITIES.items())


def _safe(s: str) -> str:
    """Escape curly braces so user-supplied text never collides with str.format placeholders."""
    return (s or "").replace("{", "{{").replace("}", "}}")


def _extract_json(raw: str) -> str:
    """Strip code fences if the model wraps JSON in them."""
    raw = raw.strip()
    if raw.startswith("```"):
        m = re.search(r"```(?:json)?\s*(.+?)```", raw, re.DOTALL)
        if m:
            return m.group(1).strip()
    return raw


def build_plan(
    *,
    message: str,
    user_id: str,
    user_context: dict,
    chat_summary: str,
    plan_summary: str,
) -> Plan:
    """Ask the planner LLM for a Plan; validate; raise on failure so caller can fall back."""
    prompt = _PROMPT.format(
        agent_catalog=_agent_catalog(),
        user_id=_safe(user_id),
        user_context=_safe(json.dumps(user_context, default=str)),
        chat_summary=_safe(chat_summary or "No prior conversation."),
        plan_summary=_safe(plan_summary or "None."),
        message=_safe(message),
        max_steps=_MAX_STEPS,
    )
    log.info("planner_kickoff", extra={"model": _MODEL, "msg_len": len(message)})
    response = _client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text
    try:
        data = json.loads(_extract_json(raw))
        plan = Plan.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        log.warning("planner_invalid_json", extra={"err": str(exc)[:200], "raw_head": raw[:200]})
        raise

    if len(plan.steps) > _MAX_STEPS:
        plan.steps = plan.steps[:_MAX_STEPS]
        log.warning("planner_truncated", extra={"to": _MAX_STEPS})

    log.info(
        "planner_ok",
        extra={
            "n_steps": len(plan.steps),
            "agents": [s.agent for s in plan.steps],
            "has_deps": any(s.depends_on for s in plan.steps),
        },
    )
    return plan
