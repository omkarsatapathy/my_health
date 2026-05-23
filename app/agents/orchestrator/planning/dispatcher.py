"""Execute a validated Plan as a DAG: parallel where independent, sequential where required."""
import asyncio
import time
from functools import partial

from crewai import Crew, Process, Task

from app.agents.orchestrator.planning.registry import SPECIALISTS
from app.agents.orchestrator.planning.schemas import Plan, PlanStep, StepResult
from app.config import planning_config
from app.observability import get_logger

log = get_logger("orchestrator.dispatcher")

_STEP_TIMEOUT = planning_config.get("step_timeout_seconds", 45)
_TOTAL_TIMEOUT = planning_config.get("total_timeout_seconds", 90)
_MAX_PARALLEL = planning_config.get("max_parallel", 3)


def _build_task_description(
    step: PlanStep,
    user_id: str,
    upstream: dict[str, StepResult],
) -> str:
    deps_block = ""
    if step.depends_on:
        lines = []
        for dep_id in step.depends_on:
            r = upstream.get(dep_id)
            if r is None:
                continue
            lines.append(f"[{dep_id} / {r.agent}]: {r.output}")
        if lines:
            deps_block = (
                "\nUpstream results you can rely on (do NOT call tools again for these):\n"
                + "\n".join(lines)
                + "\n"
            )
    return (
        f"User ID (use this exact value for ALL tool calls): {user_id}\n\n"
        f"Task: {step.task}\n"
        f"{deps_block}\n"
        "Use ONLY your own tools. If the task is outside your scope, reply in one line "
        "naming the right domain — do NOT fabricate numbers. Always pass the exact user_id "
        "above when calling any tool."
    )


def _run_step_blocking(step: PlanStep, user_id: str, upstream: dict[str, StepResult]) -> StepResult:
    """Run a single specialist as a tiny one-task crew. Blocking — call via run_in_executor."""
    started = time.perf_counter()
    agent = SPECIALISTS.get(step.agent)
    if agent is None:
        return StepResult(
            step_id=step.id, agent=step.agent, task=step.task,
            output="", error=f"unknown agent: {step.agent}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    task = Task(
        description=_build_task_description(step, user_id, upstream),
        expected_output="Concrete numbers or a one-line scope-deferral message.",
        agent=agent,
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
    try:
        out = str(crew.kickoff())
        return StepResult(
            step_id=step.id, agent=step.agent, task=step.task,
            output=out, duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:
        log.exception("step_failed", extra={"step_id": step.id, "agent": step.agent})
        return StepResult(
            step_id=step.id, agent=step.agent, task=step.task,
            output="", error=f"{type(exc).__name__}: {exc}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


def _topo_levels(plan: Plan) -> list[list[PlanStep]]:
    """Group steps into levels where every step in level N has all deps in levels < N."""
    by_id = {s.id: s for s in plan.steps}
    placed: set[str] = set()
    levels: list[list[PlanStep]] = []
    remaining = list(plan.steps)
    while remaining:
        level = [s for s in remaining if all(d in placed for d in s.depends_on)]
        if not level:
            raise ValueError("plan has a dependency cycle")
        levels.append(level)
        for s in level:
            placed.add(s.id)
        remaining = [s for s in remaining if s.id not in placed]
    return levels


async def execute_plan(plan: Plan, user_id: str) -> list[StepResult]:
    """Run the plan, level by level, with bounded parallelism and per-step timeout."""
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(_MAX_PARALLEL)
    results: dict[str, StepResult] = {}

    async def _run_one(step: PlanStep) -> StepResult:
        async with sem:
            log.info("step_start", extra={"step_id": step.id, "agent": step.agent})
            try:
                res = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, partial(_run_step_blocking, step, user_id, dict(results))
                    ),
                    timeout=_STEP_TIMEOUT,
                )
            except asyncio.TimeoutError:
                log.warning("step_timeout", extra={"step_id": step.id, "agent": step.agent})
                res = StepResult(
                    step_id=step.id, agent=step.agent, task=step.task,
                    output="", error=f"timeout after {_STEP_TIMEOUT}s",
                )
            log.info(
                "step_done",
                extra={"step_id": step.id, "agent": step.agent, "ok": res.error is None,
                       "duration_ms": res.duration_ms},
            )
            return res

    async def _run_all() -> None:
        levels = _topo_levels(plan)
        log.info(
            "plan_structure",
            extra={
                "n_steps": len(plan.steps),
                "n_levels": len(levels),
                "levels": [[f"{s.id}:{s.agent}" for s in lvl] for lvl in levels],
            },
        )
        for level in levels:
            level_results = await asyncio.gather(*(_run_one(s) for s in level))
            for r in level_results:
                results[r.step_id] = r

    try:
        await asyncio.wait_for(_run_all(), timeout=_TOTAL_TIMEOUT)
    except asyncio.TimeoutError:
        log.warning("plan_total_timeout", extra={"total_timeout_s": _TOTAL_TIMEOUT})

    # Preserve original plan order in the returned list.
    return [results[s.id] for s in plan.steps if s.id in results]
