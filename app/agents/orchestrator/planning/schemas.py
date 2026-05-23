from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

AgentName = Literal[
    "nutrition", "fitness", "physician", "motivation",
    "intake", "progress", "consult", "dashboard", "lifestyle",
]


class PlanStep(BaseModel):
    """A single specialist invocation in a plan."""
    id: str = Field(..., min_length=1, max_length=8)
    agent: AgentName
    task: str = Field(..., min_length=4, max_length=400)
    depends_on: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    """A planner-produced DAG of specialist invocations."""
    reasoning: str = Field(default="", max_length=400)
    steps: list[PlanStep]

    @field_validator("steps")
    @classmethod
    def _non_empty_unique_ids(cls, steps: list[PlanStep]) -> list[PlanStep]:
        if not steps:
            raise ValueError("plan must have at least one step")
        ids = [s.id for s in steps]
        if len(set(ids)) != len(ids):
            raise ValueError("step ids must be unique")
        valid = set(ids)
        for s in steps:
            for dep in s.depends_on:
                if dep not in valid:
                    raise ValueError(f"step {s.id} depends on unknown id {dep}")
                if dep == s.id:
                    raise ValueError(f"step {s.id} cannot depend on itself")
        return steps


class StepResult(BaseModel):
    """Captured output from one executed plan step."""
    step_id: str
    agent: str
    task: str
    output: str
    error: Optional[str] = None
    duration_ms: int = 0
