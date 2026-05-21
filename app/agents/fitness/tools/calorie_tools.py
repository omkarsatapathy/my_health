from typing import Any

from app.observability import traced_tool as tool


_MET_TABLE: dict[str, float] = {
    "walking_brisk": 4.3,
    "jogging": 7.0,
    "running": 9.8,
    "treadmill_incline": 8.5,
    "cycling_moderate": 7.5,
    "elliptical": 5.0,
    "weightlifting_light": 3.5,
    "weightlifting_heavy": 6.0,
    "bodyweight_hiit": 8.0,
    "yoga": 3.0,
}


def _calculate_calories_burned(
    exercise_type: str,
    duration_min: float,
    user_weight_kg: float,
) -> dict[str, Any]:
    """MET-based kcal estimate: kcal = MET * weight_kg * hours."""
    key = exercise_type.lower().replace(" ", "_")
    met = _MET_TABLE.get(key)

    if met is None:
        return {
            "error": f"unknown exercise_type: {exercise_type}",
            "supported": list(_MET_TABLE.keys()),
        }

    kcal = met * user_weight_kg * (duration_min / 60.0)
    return {
        "exercise_type": key,
        "met": met,
        "duration_min": duration_min,
        "user_weight_kg": user_weight_kg,
        "est_kcal_burned": round(kcal, 1),
    }


@tool("calculate_calories_burned")
def calculate_calories_burned(
    exercise_type: str,
    duration_min: float,
    user_weight_kg: float,
) -> dict[str, Any]:
    """MET-based calorie burn estimate for a single exercise; no LLM call."""
    return _calculate_calories_burned(exercise_type, duration_min, user_weight_kg)
