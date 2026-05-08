import asyncio
from functools import partial

from crewai import Agent, Crew, LLM, Process, Task

from app.config import llm_config, settings
from app.agents.nutrition.agent import nutrition_agent
from app.agents.orchestrator.tools.intent_tools import (
    classify_intent,
    load_user_context,
    write_lt_memory,
)
from app.agents.orchestrator.tools.profile_tools import (
    get_user_profile,
    update_user_profile,
)

_haiku_llm = LLM(
    model=f"anthropic/{llm_config['anthropic']['chat_model']}",
    api_key=settings.anthropic_api_key,
    temperature=llm_config["temperature"],
)

# Context agent: loads user state, classifies intent, writes memory after each turn
_context_agent = Agent(
    role="Session Context Manager",
    goal=(
        "Load user long-term context, classify the intent of the query, "
        "and persist key facts back to memory after each turn."
    ),
    backstory=(
        "You are the first agent to handle every user request. "
        "You load the user's health profile and memory, classify their intent, "
        "and ensure new facts are saved at the end of each conversation turn."
    ),
    llm=_haiku_llm,
    tools=[
        classify_intent,
        load_user_context,
        write_lt_memory,
        get_user_profile,
        update_user_profile,
    ],
    verbose=False,
)


def _run_orchestrator(user_id: str, user_context: str, chat_summary: str) -> str:
    """Synchronous hierarchical crew kickoff — run inside a thread pool."""
    context_task = Task(
        description=(
            f"User ID: {user_id}\n"
            f"User message: {user_context}\n\n"
            "1. Call load_user_context to retrieve the user's long-term health profile.\n"
            "2. Call classify_intent on the user message.\n"
            "3. Return a JSON summary with intent label, confidence, and the full user context."
        ),
        expected_output="JSON with intent, confidence, and user_context object.",
        agent=_context_agent,
    )

    response_task = Task(
        description=(
            f"User ID (use this exact value for ALL tool calls): {user_id}\n\n"
            f"Recent chat history:\n{chat_summary}\n\n"
            f"User message: {user_context}\n\n"
            "Using the intent and user context from the previous task:\n"
            "- For food/meal/water/diet/macro queries → use your nutrition tools to log or analyse.\n"
            "  IMPORTANT: always pass the user_id above when calling any tool.\n"
            "- Generate a concise, warm, actionable reply with specific numbers where available.\n"
            "- Call write_lt_memory if new facts were learned (weight, goals, preferences).\n"
            "- Append a medical disclaimer only for symptom or clinical queries."
        ),
        expected_output=(
            "A concise, warm, actionable health response with specific numbers where available."
        ),
        agent=nutrition_agent,
        context=[context_task],
    )

    crew = Crew(
        agents=[_context_agent, nutrition_agent],
        tasks=[context_task, response_task],
        process=Process.sequential,
        verbose=False,
    )

    result = crew.kickoff(inputs={"user_id": user_id})
    return str(result)


async def run_orchestrator(user_id: str, user_context: str, chat_summary: str) -> str:
    """Async wrapper — offloads blocking CrewAI kickoff to a thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, partial(_run_orchestrator, user_id, user_context, chat_summary)
    )
