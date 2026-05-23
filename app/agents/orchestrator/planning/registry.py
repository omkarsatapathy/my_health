"""Single source of truth for which planner-name maps to which specialist agent."""
from crewai import Agent

from app.agents.consult.agent import consult_agent
from app.agents.dashboard.agent import dashboard_agent
from app.agents.fitness.agent import fitness_agent
from app.agents.intake.agent import intake_agent
from app.agents.lifestyle.agent import lifestyle_agent
from app.agents.motivation.agent import motivation_agent
from app.agents.nutrition.agent import nutrition_agent
from app.agents.physician.agent import physician_agent
from app.agents.progress.agent import progress_agent

SPECIALISTS: dict[str, Agent] = {
    "nutrition": nutrition_agent,
    "fitness": fitness_agent,
    "physician": physician_agent,
    "motivation": motivation_agent,
    "intake": intake_agent,
    "progress": progress_agent,
    "consult": consult_agent,
    "dashboard": dashboard_agent,
    "lifestyle": lifestyle_agent,
}

# Short capability blurbs the planner sees. Keep tight — planner uses these to pick agents.
CAPABILITIES: dict[str, str] = {
    "nutrition": (
        "Logs meals/water; reads single-day calories, macros, water totals; generates Indian meal plans. "
        "Use for: today/yesterday food, calories-in, hydration, macro breakdown, kirana meal ideas."
    ),
    "fitness": (
        "Logs workouts; reads single-day workout history, calories burned, recovery; suggests next session. "
        "Use for: today/yesterday workout, cardio/gym sessions, burn estimates, rest-day calls."
    ),
    "physician": (
        "Logs weight; reads current weight, BMI, sedentary risk; generates monthly health report. "
        "Use for: today's weight, BMI, body-fat, vitals snapshot."
    ),
    "motivation": (
        "Reads streaks, yesterday's deficit, today's burn target, weekly challenges; schedules nudges. "
        "Use for: streak count, motivational framing, reminders, deficit/surplus narrative."
    ),
    "intake": (
        "Stores/updates medical baseline: allergies, conditions, meds, surgeries, long-term goals. "
        "Use for: 'I'm allergic to X', 'diagnosed with Y', stating a target weight or goal."
    ),
    "progress": (
        "Reads MULTI-DAY trend (>=7 days): weight slope, calorie balance, workout consistency, goal ETA. "
        "Use for: trend/plateau/'am I on track', week-vs-week, month-over-month. NEVER single-day lookups."
    ),
    "consult": (
        "LLM-only (no DB) — answers symptom questions, first aid, supplements; appends medical disclaimer. "
        "Use for: pain/symptoms, injury first-aid, supplement queries, red-flag escalation."
    ),
    "dashboard": (
        "Produces JSON chart payloads only: period summaries, chart series, streak boards. "
        "Use ONLY when user explicitly asks for chart/graph/heatmap/visual."
    ),
    "lifestyle": (
        "Onboarding interview + the 1500-word lifestyle plan doc that other agents read. "
        "Use for: starting/editing a plan, stating 'my why', re-planning after target reached."
    ),
}
