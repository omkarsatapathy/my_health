import json
from typing import Any

import anthropic
from app.observability import traced_tool as tool

from app.config import prompt_templates, settings
from app.core.db import query_sk_prefix

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
_NUTRITION_FACTS_PROMPT: str = prompt_templates["get_food_nutrition_facts"]

_TARGET_SPLIT = {"protein": 25.0, "carbs": 50.0, "fat": 25.0}
_TOLERANCE = 10.0


def _get_food_nutrition_facts(food_name: str) -> dict[str, Any]:
    """Ask Claude for per-100g macros of a named food; returns structured JSON."""
    prompt = _NUTRITION_FACTS_PROMPT.format(food_name=food_name)
    response = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def _calculate_macro_balance(user_id: str, date: str) -> dict[str, Any]:
    """Read day's meals, compute protein/carb/fat % split, flag off-target macros."""
    meals = query_sk_prefix(user_id, f"MEAL#{date}")

    totals = {"protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "kcal": 0.0}
    for meal in meals:
        macros = meal.get("macros", {})
        totals["protein_g"] += float(macros.get("protein_g", 0))
        totals["carbs_g"]   += float(macros.get("carbs_g", 0))
        totals["fat_g"]     += float(macros.get("fat_g", 0))
        totals["kcal"]      += float(meal.get("total_kcal", 0))

    if totals["kcal"] == 0:
        return {"date": date, "error": "no meals logged for this date"}

    protein_kcal = totals["protein_g"] * 4
    carbs_kcal   = totals["carbs_g"]   * 4
    fat_kcal     = totals["fat_g"]     * 9
    macro_kcal_total = protein_kcal + carbs_kcal + fat_kcal or 1

    split = {
        "protein_pct": round(protein_kcal / macro_kcal_total * 100, 1),
        "carbs_pct":   round(carbs_kcal   / macro_kcal_total * 100, 1),
        "fat_pct":     round(fat_kcal     / macro_kcal_total * 100, 1),
    }

    flags = []
    if abs(split["protein_pct"] - _TARGET_SPLIT["protein"]) > _TOLERANCE:
        flags.append(f"protein off target: {split['protein_pct']}% (target {_TARGET_SPLIT['protein']}%)")
    if abs(split["carbs_pct"] - _TARGET_SPLIT["carbs"]) > _TOLERANCE:
        flags.append(f"carbs off target: {split['carbs_pct']}% (target {_TARGET_SPLIT['carbs']}%)")
    if abs(split["fat_pct"] - _TARGET_SPLIT["fat"]) > _TOLERANCE:
        flags.append(f"fat off target: {split['fat_pct']}% (target {_TARGET_SPLIT['fat']}%)")

    return {
        "date": date,
        "total_kcal": round(totals["kcal"], 1),
        "grams": {k: round(v, 1) for k, v in totals.items() if k != "kcal"},
        "split": split,
        "flags": flags,
    }


@tool("get_food_nutrition_facts")
def get_food_nutrition_facts(food_name: str) -> dict[str, Any]:
    """Return per-100g macro breakdown for any food item via LLM lookup."""
    return _get_food_nutrition_facts(food_name)


@tool("calculate_macro_balance")
def calculate_macro_balance(user_id: str, date: str) -> dict[str, Any]:
    """Compute protein/carb/fat % split for the day and flag off-target macros."""
    return _calculate_macro_balance(user_id, date)
