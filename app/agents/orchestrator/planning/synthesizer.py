"""Final-voice agent: merges step results into one coherent reply."""
from crewai import Agent, Crew, LLM, Process, Task

from app.agents.orchestrator.planning.schemas import StepResult
from app.config import llm_config, prompt_templates, settings
from app.observability import get_logger
from app.status_events import synthesizer as status_synth

log = get_logger("orchestrator.synthesizer")

SYNTHESIZER_AGENT_ROLE = "Response Synthesizer"

_model = llm_config["anthropic"].get("synthesizer_model") or llm_config["anthropic"]["chat_model"]
_llm = LLM(
    model=f"anthropic/{_model}",
    api_key=settings.anthropic_api_key,
    temperature=llm_config["temperature"],
    stream=True,
)

synthesizer_agent = Agent(
    role=SYNTHESIZER_AGENT_ROLE,
    goal="Merge multi-agent results into one warm, accurate, single-voice reply for the user.",
    backstory=(
        "You are the single voice the user hears. Multiple specialists ran in parallel and "
        "handed you their outputs. You weave them into one coherent reply, quote numbers "
        "verbatim, never invent values, and surface medical disclaimers when present."
    ),
    llm=_llm,
    tools=[],
    verbose=False,
)

_PROMPT: str = prompt_templates["synthesizer_prompt"]


def _format_step_results(results: list[StepResult]) -> str:
    blocks: list[str] = []
    for r in results:
        body = r.error and f"(no data — {r.error})" or (r.output or "(empty)")
        blocks.append(f"[{r.step_id} / {r.agent}]:\n{body}")
    return "\n\n".join(blocks) if blocks else "(no specialist results)"


def synthesize(message: str, results: list[StepResult]) -> str:
    """Run the synthesizer agent on the original message + all step outputs."""
    safe_message = message.replace("{", "{{").replace("}", "}}")
    safe_results = _format_step_results(results).replace("{", "{{").replace("}", "}}")

    desc = _PROMPT.format(message=safe_message, step_results=safe_results)
    task = Task(
        description=desc,
        expected_output="One concise, warm reply in a single voice.",
        agent=synthesizer_agent,
    )
    crew = Crew(
        agents=[synthesizer_agent], tasks=[task],
        process=Process.sequential, verbose=False,
    )
    log.info("synthesizer_kickoff", extra={"n_results": len(results)})
    status_synth("Drafting reply")
    out = str(crew.kickoff())
    log.info("synthesizer_done", extra={"reply_len": len(out or "")})
    return out
