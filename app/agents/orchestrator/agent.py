import asyncio
import re
from functools import partial

from crewai import Agent, Crew, LLM, Process, Task

from app.config import llm_config, settings
from app.agents.nutrition.agent import nutrition_agent
from app.agents.fitness.agent import fitness_agent
from app.agents.physician.agent import physician_agent
from app.agents.motivation.agent import motivation_agent
from app.agents.intake.agent import intake_agent
from app.agents.progress.agent import progress_agent
from app.agents.consult.agent import consult_agent
from app.agents.dashboard.agent import dashboard_agent
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


_FITNESS_INTENTS = {"log_workout"}
_FITNESS_KEYWORDS = (
    "gym", "workout", "exercise", "treadmill", "running", "jogging", "cardio",
    "lift", "lifting", "weights", "sets", "reps", "burn", "cycling", "elliptical",
    "hiit", "yoga", "rest day", "muscle", "strength",
)

_PHYSICIAN_INTENTS = {"weight_entry", "body_scan"}
_PHYSICIAN_KEYWORDS = (
    "bmi", "obese", "obesity", "sedentary", "health report", "monthly report",
    "weight", "weighed", "weighing", "body fat",
)

_MOTIVATION_INTENTS = {"motivation_query"}
_MOTIVATION_KEYWORDS = (
    "streak", "challenge", "nudge", "motivate", "motivation", "remind me",
    "reminder", "deficit", "surplus", "burn target", "how am i doing",
    "milestone",
)

_INTAKE_INTENTS = {"intake_query"}
_INTAKE_KEYWORDS = (
    "allergy", "allergic", "injury", "condition", "medication", "meds",
    "surgery", "history", "diagnosed", "goal", "target weight",
)

_PROGRESS_INTENTS = {"progress_query"}
_PROGRESS_KEYWORDS = (
    "report", "trend", "on track", "progress", "overview", "snapshot",
)

_DASHBOARD_INTENTS = {"view_dashboard"}
_DASHBOARD_KEYWORDS = (
    "dashboard", "chart", "graph", "heatmap", "streak board", "summary card",
    "last week", "last month", "weekly summary", "monthly summary",
)

_CONSULT_INTENTS = {"consult_symptom", "symptom_query", "first_aid", "supplement_query"}
_CONSULT_KEYWORDS = (
    "pain", "hurt", "ache", "symptom", "headache", "fever", "dizzy", "nausea",
    "cough", "cold", "sore", "supplement", "vitamin", "whey", "creatine",
    "first aid", "burn", "sprain", "cut", "wound", "bleeding", "nosebleed",
)


def _extract_intent(context_output: str) -> str:
    """Pull the intent label out of the context task's JSON output."""
    match = re.search(r'"intent"\s*:\s*"([^"]+)"', context_output)
    return match.group(1) if match else "unknown"


def _select_specialist(intent: str, message: str):
    """Pick intake, motivation, physician, fitness, or nutrition agent from intent + keyword fallback."""
    if intent in _CONSULT_INTENTS:
        return consult_agent
    if intent in _DASHBOARD_INTENTS:
        return dashboard_agent
    if intent in _INTAKE_INTENTS:
        return intake_agent
    if intent in _PROGRESS_INTENTS:
        return progress_agent
    if intent in _MOTIVATION_INTENTS:
        return motivation_agent
    if intent in _PHYSICIAN_INTENTS:
        return physician_agent
    if intent in _FITNESS_INTENTS:
        return fitness_agent
    msg_lower = message.lower()
    if any(kw in msg_lower for kw in _CONSULT_KEYWORDS):
        return consult_agent
    if any(kw in msg_lower for kw in _DASHBOARD_KEYWORDS):
        return dashboard_agent
    if any(kw in msg_lower for kw in _INTAKE_KEYWORDS):
        return intake_agent
    if any(kw in msg_lower for kw in _PROGRESS_KEYWORDS):
        return progress_agent
    if any(kw in msg_lower for kw in _MOTIVATION_KEYWORDS):
        return motivation_agent
    if any(kw in msg_lower for kw in _FITNESS_KEYWORDS):
        return fitness_agent
    if any(kw in msg_lower for kw in _PHYSICIAN_KEYWORDS):
        return physician_agent
    return nutrition_agent


def _run_orchestrator(user_id: str, user_context: str, chat_summary: str) -> str:
    """Two-stage crew: classify intent first, then dispatch to chosen specialist."""
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

    context_crew = Crew(
        agents=[_context_agent],
        tasks=[context_task],
        process=Process.sequential,
        verbose=False,
    )
    context_result = str(context_crew.kickoff(inputs={"user_id": user_id}))

    intent = _extract_intent(context_result)
    specialist = _select_specialist(intent, user_context)

    # Sanitize chat_summary / user_context against CrewAI's str.format-style
    # interpolation: any stray "{key}" in user-supplied text would otherwise
    # raise KeyError on Crew.kickoff.
    safe_chat_summary = chat_summary.replace("{", "{{").replace("}", "}}")
    safe_user_context = user_context.replace("{", "{{").replace("}", "}}")

    response_task = Task(
        description=(
            f"User ID (use this exact value for ALL tool calls): {user_id}\n\n"
            f"Classified intent: {intent}\n\n"
            f"Recent chat history:\n{safe_chat_summary}\n\n"
            f"User message: {safe_user_context}\n\n"
            "Routing rules:\n"
            "- Food / meal / water / diet / macro queries -> use nutrition tools.\n"
            "- Workout / gym / cardio / strength / rest-day / burn-target queries -> use fitness tools.\n"
            "- Weight / BMI / sedentary risk / monthly health report queries -> use physician tools.\n"
            "- Streaks / weekly challenge / nudges / deficit summary / motivation / reminders -> use motivation tools.\n"
            "- Allergies / conditions / medications / surgeries / health history / goal setting -> use intake tools.\n"
            "- Cross-domain progress / trend report / goal tracking -> use progress tools.\n"
            "- Dashboard cards / charts / heatmaps / streak board (chart-ready payloads) -> use dashboard tools.\n"
            "- Symptoms / pain / first aid / supplements / post-workout soreness -> use consult agent (no tools, LLM-only). Always include the medical disclaimer.\n\n"
            "Special instructions:\n"
            "- For meal history queries (e.g., 'what did I eat yesterday?', 'show my meals'), use get_daily_calorie_log with date='yesterday', 'today', or YYYY-MM-DD.\n"
            "- ALWAYS pass the exact user_id when calling any tool.\n"
            "- If the agent doesn't have the right tools, explain what data would be needed.\n\n"
            "Generate a concise, warm, actionable reply with specific numbers where available. "
            "Append a medical disclaimer only for symptom or clinical queries."
        ),
        expected_output=(
            "A concise, warm, actionable health response with specific numbers where available."
        ),
        agent=specialist,
    )

    response_crew = Crew(
        agents=[specialist],
        tasks=[response_task],
        process=Process.sequential,
        verbose=False,
    )

    return str(response_crew.kickoff())


async def run_orchestrator(user_id: str, user_context: str, chat_summary: str) -> str:
    """Async wrapper — offloads blocking CrewAI kickoff to a thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_run_orchestrator, user_id, user_context, chat_summary)
    )
