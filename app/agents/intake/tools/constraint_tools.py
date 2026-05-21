from typing import Any

from app.observability import traced_tool as tool

from app.core.db import get_item
from app.agents.intake.tools.history_tools import _normalize_list


_HIGH_RISK_CONDITIONS = {
    "hypertension", "high blood pressure", "diabetes", "type 2 diabetes",
    "type 1 diabetes", "cardiac", "heart disease", "ckd", "kidney disease",
    "asthma", "copd", "pregnancy", "pregnant",
}

_JOINT_CONDITIONS = {"knee injury", "back pain", "slipped disc", "arthritis", "sciatica"}
_HIGH_IMPACT_EXERCISES = {"running", "jogging", "hiit", "jump", "sprint", "burpee"}


def _check_constraints(
    user_id: str,
    proposed_type: str,
    proposed_text: str,
) -> dict[str, Any]:
    """Match a proposed food or exercise against stored allergies, conditions, medications."""
    history = get_item(user_id, "INTAKE#history") or {}
    allergies = [a.lower() for a in _normalize_list(history.get("allergies"))]
    conditions = [c.lower() for c in _normalize_list(history.get("conditions"))]

    text = (proposed_text or "").lower()
    ptype = (proposed_type or "").lower().strip()

    blocks: list[str] = []
    flags: list[str] = []

    if ptype in {"food", "meal"}:
        for allergen in allergies:
            if allergen and allergen in text:
                blocks.append(f"contains allergen: {allergen}")

    if ptype in {"exercise", "workout", "plan"}:
        joint_hits = [c for c in conditions if c in _JOINT_CONDITIONS]
        impact_hits = [e for e in _HIGH_IMPACT_EXERCISES if e in text]
        if joint_hits and impact_hits:
            blocks.append(
                f"high-impact ({', '.join(impact_hits)}) conflicts with {', '.join(joint_hits)}"
            )

    high_risk_hits = [c for c in conditions if c in _HIGH_RISK_CONDITIONS]
    if high_risk_hits:
        flags.append(f"chronic conditions on file: {', '.join(high_risk_hits)}")

    if blocks:
        risk_level = "high"
    elif flags:
        risk_level = "moderate"
    else:
        risk_level = "low"

    return {
        "proposed_type": ptype,
        "proposed_text": proposed_text,
        "blocks": blocks,
        "flags": flags,
        "risk_level": risk_level,
        "allergies_on_file": allergies,
        "conditions_on_file": conditions,
    }


@tool("check_constraints")
def check_constraints(user_id: str, proposed_type: str, proposed_text: str) -> dict[str, Any]:
    """Validate a proposed food/exercise/plan against the user's stored allergies and conditions. proposed_type is one of food|meal|exercise|workout|plan."""
    return _check_constraints(user_id, proposed_type, proposed_text)
