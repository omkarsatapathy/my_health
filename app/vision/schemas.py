from typing import Any, Literal, Optional
from pydantic import BaseModel


class FoodAnalysis(BaseModel):
    image_type: Literal["food"]
    calories: Optional[float] = None
    carbs_g: Optional[float] = None
    protein_g: Optional[float] = None
    fat_g: Optional[float] = None
    sugar_g: Optional[float] = None
    fiber_g: Optional[float] = None
    sodium_mg: Optional[float] = None
    vitamins: Optional[dict[str, Any]] = None
    portion_size: Optional[str] = None
    food_items: Optional[list[str]] = None


class TreadmillAnalysis(BaseModel):
    image_type: Literal["treadmill"]
    total_steps: Optional[int] = None
    calories_burned: Optional[float] = None
    time_minutes: Optional[float] = None
    distance_km: Optional[float] = None
    speed_kmh: Optional[float] = None
    incline_percent: Optional[float] = None
    heart_rate_bpm: Optional[int] = None


class WorkoutAnalysis(BaseModel):
    image_type: Literal["workout"]
    calories_burned: Optional[float] = None
    exercise_type: Optional[str] = None
    duration_minutes: Optional[float] = None
    reps: Optional[int] = None
    sets: Optional[int] = None
    muscle_groups: Optional[list[str]] = None


class GeneralAnalysis(BaseModel):
    image_type: Literal["other"]
    observations: Optional[list[str]] = None
    health_relevance: Optional[str] = None


class ImageAnalysisResult(BaseModel):
    """Unified result from vision processor."""
    image_type: str
    structured_data: dict[str, Any]
    description: str  # max 300 words, health-focused summary
