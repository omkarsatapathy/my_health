import asyncio
from functools import partial

from crewai import Agent, Crew, LLM, Process, Task

from app.config import llm_config, settings

_ORCHESTRATOR_MODEL = f"anthropic/{llm_config['anthropic']['orchestrator_model']}"

_orchestrator_llm = LLM(
    model=_ORCHESTRATOR_MODEL,
    api_key=settings.anthropic_api_key,
    temperature=llm_config["temperature"],
)

_orchestrator_agent = Agent(
    role="Health Coach Orchestrator",
    goal=(
        "Analyze user health queries — including meal images, workout data, and wellness questions — "
        "and provide comprehensive, personalized health guidance."
    ),
    backstory=(
        "You are a senior health coach with expertise in nutrition, fitness, and preventive wellness. "
        "You coordinate specialist knowledge across dietetics, exercise science, and general medicine "
        "to give users accurate, actionable, and empathetic health advice. "
        "For Indian users, you prioritize affordable local ingredients and accessible exercises. "
        "You always append a medical disclaimer for clinical or symptom-related questions."
    ),
    llm=_orchestrator_llm,
    tools=[],  # sub-agent tools will be wired here later
    verbose=False,
)


def _run_orchestrator(user_context: str, chat_summary: str) -> str:
    """Synchronous crew kickoff — run inside a thread pool from async callers."""
    task = Task(
        description=(
            f"Chat history summary:\n{chat_summary}\n\n"
            f"Current user query (with any image analysis included):\n{user_context}"
        ),
        agent=_orchestrator_agent,
        expected_output=(
            "A concise, warm, and actionable health response addressing the user's query. "
            "Include specific numbers (calories, macros, reps, etc.) when available from image data. "
            "Add a medical disclaimer only when the query involves symptoms or clinical concerns."
        ),
    )

    crew = Crew(
        agents=[_orchestrator_agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    )

    result = crew.kickoff()
    print("[Orchestrator] Final response:", result)
    return str(result)


async def run_orchestrator(user_context: str, chat_summary: str) -> str:
    """Async wrapper — offloads blocking CrewAI kickoff to a thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, partial(_run_orchestrator, user_context, chat_summary)
    )
