from crewai import Agent, LLM

from app.config import agent_goals, llm_config, prompt_templates, settings
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
    goal=agent_goals["motivation_goal"],
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
