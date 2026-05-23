import asyncio
import re
from functools import partial

from crewai import Agent, Crew, LLM, Process, Task

from app.config import agent_goals, llm_config, planning_config, settings
from app.core.db import get_item
from app.observability import get_logger, user_id_var

log = get_logger("orchestrator")
from app.agents.nutrition.agent import nutrition_agent
from app.agents.fitness.agent import fitness_agent
from app.agents.physician.agent import physician_agent
from app.agents.motivation.agent import motivation_agent
from app.agents.intake.agent import intake_agent
from app.agents.progress.agent import progress_agent
from app.agents.consult.agent import consult_agent
from app.agents.dashboard.agent import dashboard_agent
from app.agents.lifestyle.agent import lifestyle_agent
from app.agents.orchestrator.planning.executor import run_planner_path, should_use_planner
from app.agents.orchestrator.tools.intent_tools import (
    _classify_intent,
    _load_user_context,
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
    goal=agent_goals["orchestrator_goal"],
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
    "trend", "on track", "plateau", "goal eta", "goal progress",
    "over the last", "over the past", "this week vs", "month-over-month",
    "weekly comparison", "monthly comparison", "progress snapshot",
)
# Daily-lookup tokens that should NEVER route to progress even if "progress"-ish
# keywords appear. Used as a veto inside _select_specialist.
_DAILY_LOOKUP_TOKENS = (
    "today", "yesterday", "right now", "currently", "this morning",
)

_DASHBOARD_INTENTS = {"view_dashboard"}
_DASHBOARD_KEYWORDS = (
    "dashboard", "chart", "graph", "heatmap", "streak board", "summary card",
    "last week", "last month", "weekly summary", "monthly summary",
)

_LIFESTYLE_INTENTS = {"lifestyle_planning"}
_LIFESTYLE_KEYWORDS = (
    "plan", "onboarding", "lifestyle", "why now", "starting fresh",
    "my why", "re-plan", "replan", "transformation",
)

_CONSULT_INTENTS = {"consult_symptom", "symptom_query", "first_aid", "supplement_query"}
_CONSULT_KEYWORDS = (
    "pain", "hurt", "ache", "symptom", "headache", "fever", "dizzy", "nausea",
    "cough", "cold", "sore", "supplement", "vitamin", "whey", "creatine",
    "first aid", "burn", "sprain", "cut", "wound", "bleeding", "nosebleed",
)

_NUTRITION_INTENTS = {"log_food", "ask_advice"}


def _kw_hit(text: str, keywords) -> bool:
    """Word-boundary keyword match — avoids 'burn' matching 'burnt onions'."""
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw)}\b", text):
            return True
    return False


def _extract_intent(context_output: str) -> str:
    """Pull the intent label out of the context task's JSON output."""
    match = re.search(r'"intent"\s*:\s*"([^"]+)"', context_output)
    return match.group(1) if match else "unknown"


def _select_specialist(intent: str, message: str):
    """Pick intake, motivation, physician, fitness, or nutrition agent from intent + keyword fallback."""
    msg_lower = message.lower()
    is_daily_lookup = any(tok in msg_lower for tok in _DAILY_LOOKUP_TOKENS)

    # Veto: daily-value lookups never go to progress/dashboard even if the
    # classifier slipped. Re-route to the right domain agent by keyword.
    if is_daily_lookup and intent in (_PROGRESS_INTENTS | _DASHBOARD_INTENTS):
        if _kw_hit(msg_lower, _FITNESS_KEYWORDS):
            return fitness_agent
        if _kw_hit(msg_lower, _PHYSICIAN_KEYWORDS):
            return physician_agent
        return nutrition_agent

    if intent in _NUTRITION_INTENTS:
        return nutrition_agent
    if intent in _LIFESTYLE_INTENTS:
        return lifestyle_agent
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
    if _kw_hit(msg_lower, _LIFESTYLE_KEYWORDS):
        return lifestyle_agent
    if _kw_hit(msg_lower, _CONSULT_KEYWORDS):
        return consult_agent
    if _kw_hit(msg_lower, _DASHBOARD_KEYWORDS):
        return dashboard_agent
    if _kw_hit(msg_lower, _INTAKE_KEYWORDS):
        return intake_agent
    if _kw_hit(msg_lower, _PROGRESS_KEYWORDS) and not is_daily_lookup:
        return progress_agent
    if _kw_hit(msg_lower, _MOTIVATION_KEYWORDS):
        return motivation_agent
    if _kw_hit(msg_lower, _FITNESS_KEYWORDS):
        return fitness_agent
    if _kw_hit(msg_lower, _PHYSICIAN_KEYWORDS):
        return physician_agent
    return nutrition_agent


def _get_plan_block(user_id: str) -> tuple[str, str]:
    """Return (raw_plan_summary, formatted_plan_block_for_prompt)."""
    plan = get_item(user_id, "LIFESTYLE#plan") or {}
    replan = get_item(user_id, "LIFESTYLE#replan_needed") or {}
    plan_summary = plan.get("plan_text_condensed") or ""
    safe = plan_summary.replace("{", "{{").replace("}", "}}")
    block = (
        f"\nACTIVE LIFESTYLE PLAN (binding context for all advice):\n{safe}\n"
        if safe else ""
    )
    if replan and replan.get("reason") == "target_reached":
        block += (
            "\nNOTE: User has reached their target weight. If relevant, suggest a fresh lifestyle plan.\n"
        )
    return plan_summary, block


def _run_fast_path(
    user_id: str,
    user_context: str,
    chat_summary: str,
    intent: str,
) -> str:
    """Single-specialist fast path. Caller has already classified the intent."""
    specialist = _select_specialist(intent, user_context)
    log.info(
        "specialist_selected",
        extra={"intent": intent, "agent_role": getattr(specialist, "role", "?")},
    )

    safe_chat_summary = chat_summary.replace("{", "{{").replace("}", "}}")
    safe_user_context = user_context.replace("{", "{{").replace("}", "}}")
    _, plan_block = _get_plan_block(user_id)

    response_task = Task(
        description=(
            f"User ID (use this exact value for ALL tool calls): {user_id}\n\n"
            f"Classified intent: {intent}\n\n"
            f"Recent chat history:\n{safe_chat_summary}\n\n"
            f"User message: {safe_user_context}\n"
            f"{plan_block}\n"
            "Routing rules (TIME WINDOW matters — single-day = domain agent; multi-day = progress):\n"
            "- Single-day food / meal / water / macro / calories-in (today / yesterday / specific date)\n"
            "  -> Nutrition. For lookups call get_daily_calorie_log(date=...).\n"
            "- Single-day workout / calories-burned (today / yesterday / specific date) -> Fitness.\n"
            "- Single-day weight / BMI / current body metrics -> Physician.\n"
            "- Multi-day TREND, plateau, goal ETA, on-track status, week-vs-week, month-over-month\n"
            "  -> Progress. NEVER use Progress for 'what is my X today/yesterday'.\n"
            "- Streaks / weekly challenge / nudges / deficit framing / reminders -> Motivation.\n"
            "- Allergies / conditions / medications / surgeries / long-term goal setting -> Intake.\n"
            "- Charts / graphs / heatmaps / streak board (visual payloads only) -> Dashboard.\n"
            "  A plain-text 'how much X' is NOT a dashboard request.\n"
            "- Symptoms / pain / first aid / supplements / post-workout soreness -> Consult\n"
            "  (LLM-only). Always include the medical disclaimer.\n\n"
            "Hard rules:\n"
            "- If the user asks for TODAY'S or YESTERDAY'S value of any metric, do NOT route to\n"
            "  Progress or Dashboard. Use the domain agent and its single-day tool.\n"
            "- If the chosen agent does not own the right tool for this query, reply in ONE line\n"
            "  naming the correct agent — do not fabricate numbers.\n"
            "- ALWAYS pass the exact user_id above when calling any tool.\n"
            "- Append the medical disclaimer only for symptom / clinical queries.\n\n"
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

    log.info("response_crew_kickoff", extra={"agent_role": getattr(specialist, "role", "?")})
    try:
        result = str(response_crew.kickoff())
    except Exception:
        log.exception("response_crew_failed", extra={"agent_role": getattr(specialist, "role", "?")})
        raise
    log.info("orchestrator_done", extra={"reply_len": len(result or "")})
    return result


def _run_orchestrator(user_id: str, user_context: str, chat_summary: str) -> str:
    """Sync fast-path entry. Streaming layer calls this directly inside a thread."""
    user_id_var.set(user_id or "-")
    log.info(
        "orchestrator_start",
        extra={"msg_len": len(user_context or ""), "history_len": len(chat_summary or "")},
    )
    intent_result = _classify_intent(user_context)
    intent = intent_result.get("intent", "unknown")
    log.info(
        "intent_classified",
        extra={"intent": intent, "confidence": intent_result.get("confidence")},
    )
    return _run_fast_path(user_id, user_context, chat_summary, intent)


async def run_orchestrator(user_id: str, user_context: str, chat_summary: str) -> str:
    """Async entry. Picks planner path for compound/low-confidence queries, fast path otherwise."""
    user_id_var.set(user_id or "-")
    loop = asyncio.get_running_loop()
    log.info(
        "orchestrator_async_start",
        extra={"msg_len": len(user_context or ""), "history_len": len(chat_summary or "")},
    )

    intent_result = await loop.run_in_executor(None, _classify_intent, user_context)
    intent = intent_result.get("intent", "unknown")
    log.info(
        "intent_classified",
        extra={"intent": intent, "confidence": intent_result.get("confidence")},
    )

    if should_use_planner(user_context, intent_result):
        log.info("route_decision", extra={"path": "planner"})
        ctx = await loop.run_in_executor(None, _load_user_context, user_id)
        plan_summary, _ = await loop.run_in_executor(None, _get_plan_block, user_id)
        reply = await run_planner_path(
            user_id=user_id,
            message=user_context,
            chat_summary=chat_summary,
            user_context=ctx,
            plan_summary=plan_summary,
        )
        if reply is not None:
            return reply
        log.warning("planner_path_fallback_to_fast")

    log.info("route_decision", extra={"path": "fast", "intent": intent})
    return await loop.run_in_executor(
        None, partial(_run_fast_path, user_id, user_context, chat_summary, intent),
    )
