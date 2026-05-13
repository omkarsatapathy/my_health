from crewai import Agent, LLM

from app.config import llm_config, prompt_templates, settings
from app.agents.motivation.tools.streak_tools import (
    get_streak_data,
    update_streak,
)
from app.agents.motivation.tools.nudge_tools import (
    get_activity_summary,
    schedule_push_notification,
    get_weekly_challenge,
)

_llm = LLM(
    model=f"anthropic/{llm_config['anthropic']['chat_model']}",
    api_key=settings.anthropic_api_key,
    temperature=llm_config["temperature"],
    stream=True,
)

MOTIVATION_AGENT_ROLE = "Motivational Coach"

motivation_agent = Agent(
    role=MOTIVATION_AGENT_ROLE,
    goal=(
        "Track streaks, surface yesterday's deficit and today's burn target, "
        "escalate on inactivity, run weekly challenges, and schedule push nudges. "
        "Adapt tone to the user's motivator_persona."
    ),
    backstory=prompt_templates["motivation_system_prompt"],
    llm=_llm,
    tools=[
        get_activity_summary,
        get_streak_data,
        update_streak,
        get_weekly_challenge,
        schedule_push_notification,
    ],
    verbose=False,
)
