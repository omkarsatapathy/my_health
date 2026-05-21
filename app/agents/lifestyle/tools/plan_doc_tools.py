import json
from datetime import datetime, timezone
from typing import Any

import anthropic
from app.observability import traced_tool as tool

from app.config import llm_config, prompt_templates, settings
from app.core.db import get_item, put_item, query_sk_prefix


_PLAN_SK = "LIFESTYLE#plan"
_STATE_SK = "LIFESTYLE#plan_state"
_DOC_TEMPLATE: str = prompt_templates["lifestyle_doc_template"]

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _latest(items: list[dict]) -> dict | None:
    if not items:
        return None
    return sorted(items, key=lambda e: e.get("sk", ""))[-1]


def _gather_inputs(user_id: str) -> dict[str, Any]:
    state = get_item(user_id, _STATE_SK) or {}
    history = get_item(user_id, "INTAKE#history") or {}
    goal = get_item(user_id, "INTAKE#goal") or {}
    vitals = _latest(query_sk_prefix(user_id, "LIFESTYLE#vitals#")) or {}
    body = _latest(query_sk_prefix(user_id, "LIFESTYLE#body_assessment#")) or {}
    return {
        "answers": state.get("answers") or {},
        "history": {k: v for k, v in history.items() if k not in ("pk", "sk")},
        "goal": {k: v for k, v in goal.items() if k not in ("pk", "sk")},
        "latest_vitals": {k: v for k, v in vitals.items() if k not in ("pk", "sk")},
        "latest_body_assessment": body.get("structured_text"),
    }


def _llm_generate(inputs: dict[str, Any]) -> dict[str, str]:
    model = llm_config["anthropic"]["chat_model"]
    prompt = (
        f"{_DOC_TEMPLATE}\n\n"
        f"User inputs (JSON):\n{json.dumps(inputs, default=str, indent=2)}\n\n"
        'Return ONLY valid JSON: {"plan_text": "<~1500 words>", "plan_text_condensed": "<~200 words>"}'
    )
    resp = _get_client().messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("`").strip()
    data = json.loads(raw)
    return {
        "plan_text": data.get("plan_text", "").strip(),
        "plan_text_condensed": data.get("plan_text_condensed", "").strip(),
    }


def _generate_plan_doc(user_id: str) -> dict[str, Any]:
    """Synthesize the 1500-word lifestyle plan + condensed summary from gathered inputs."""
    inputs = _gather_inputs(user_id)
    doc = _llm_generate(inputs)
    goal = inputs.get("goal") or {}
    answers = inputs.get("answers") or {}
    return {
        "plan_text": doc["plan_text"],
        "plan_text_condensed": doc["plan_text_condensed"],
        "target_kg": str(answers.get("target_kg") or goal.get("target_kg") or ""),
        "goal_type": answers.get("transformation_focus") or goal.get("goal_type") or "maintain",
    }


def _save_plan_doc(
    user_id: str,
    plan_text: str,
    plan_text_condensed: str,
    target_kg: str | None = None,
    goal_type: str | None = None,
) -> dict[str, Any]:
    """Write LIFESTYLE#plan as active, archive prior version under LIFESTYLE#plan#v<ts>."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prior = get_item(user_id, _PLAN_SK)
    version = 1
    if prior:
        version = int(prior.get("version", 1)) + 1
        archive_sk = f"LIFESTYLE#plan#v{prior.get('updated_at', now)}"
        archive = {k: v for k, v in prior.items() if k not in ("pk", "sk")}
        put_item(user_id=user_id, sk=archive_sk, data=archive)

    record = {
        "plan_text": plan_text,
        "plan_text_condensed": plan_text_condensed,
        "created_at": prior.get("created_at") if prior else now,
        "updated_at": now,
        "version": version,
        "status": "active",
        "target_kg": target_kg or "",
        "goal_type": goal_type or "maintain",
    }
    put_item(user_id=user_id, sk=_PLAN_SK, data=record)
    # clear the replan flag if it was set
    flag = get_item(user_id, "LIFESTYLE#replan_needed")
    if flag:
        put_item(user_id=user_id, sk="LIFESTYLE#replan_needed", data={"reason": "cleared", "cleared_at": now})
    return {"status": "saved", "version": version, "updated_at": now}


def _get_plan_doc(user_id: str) -> dict[str, Any]:
    record = get_item(user_id, _PLAN_SK)
    if not record:
        return {"status": "not_found"}
    return {
        "status": "active",
        "plan_text": record.get("plan_text"),
        "plan_text_condensed": record.get("plan_text_condensed"),
        "version": record.get("version"),
        "updated_at": record.get("updated_at"),
        "target_kg": record.get("target_kg"),
        "goal_type": record.get("goal_type"),
    }


def _patch_plan_doc(user_id: str, edit_instruction: str) -> dict[str, Any]:
    """LLM-rewrite the active plan doc per the user's instruction; persist as new version."""
    current = get_item(user_id, _PLAN_SK)
    if not current:
        return {"status": "not_found", "message": "No active plan to edit."}

    model = llm_config["anthropic"]["chat_model"]
    prompt = (
        "You are editing a personal lifestyle plan document. Apply the user's instruction "
        "minimally — preserve sections and tone, change only what is asked.\n\n"
        f"Edit instruction: {edit_instruction}\n\n"
        f"Current plan_text:\n{current.get('plan_text', '')}\n\n"
        'Return ONLY valid JSON: {"plan_text": "<updated full doc>", "plan_text_condensed": "<~200 words>"}'
    )
    resp = _get_client().messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("`").strip()
    data = json.loads(raw)
    return _save_plan_doc(
        user_id,
        plan_text=data.get("plan_text", current.get("plan_text", "")),
        plan_text_condensed=data.get("plan_text_condensed", current.get("plan_text_condensed", "")),
        target_kg=current.get("target_kg"),
        goal_type=current.get("goal_type"),
    )


@tool("generate_plan_doc")
def generate_plan_doc(user_id: str) -> dict[str, Any]:
    """Synthesize the 1500-word lifestyle plan + 200-word condensed summary from plan_state, intake history, goal, latest vitals, latest body assessment."""
    return _generate_plan_doc(user_id)


@tool("save_plan_doc")
def save_plan_doc(
    user_id: str,
    plan_text: str,
    plan_text_condensed: str,
    target_kg: str | None = None,
    goal_type: str | None = None,
) -> dict[str, Any]:
    """Persist the active lifestyle plan at LIFESTYLE#plan and archive the prior version."""
    return _save_plan_doc(user_id, plan_text, plan_text_condensed, target_kg, goal_type)


@tool("get_plan_doc")
def get_plan_doc(user_id: str) -> dict[str, Any]:
    """Return the user's active lifestyle plan document."""
    return _get_plan_doc(user_id)


@tool("patch_plan_doc")
def patch_plan_doc(user_id: str, edit_instruction: str) -> dict[str, Any]:
    """Apply a natural-language edit to the active plan doc (e.g. 'change target to 72 kg') and save a new version."""
    return _patch_plan_doc(user_id, edit_instruction)
