from crewai import Agent, LLM

from app.config import agent_goals, llm_config, prompt_templates, settings
from app.agents.dashboard.tools.summary_tools import get_period_summary
from app.agents.dashboard.tools.chart_tools import get_chart_series
from app.agents.dashboard.tools.streak_board_tools import get_streak_board

_llm = LLM(
    model=f"anthropic/{llm_config['anthropic']['chat_model']}",
    api_key=settings.anthropic_api_key,
    temperature=llm_config["temperature"],
    stream=True,
)

DASHBOARD_AGENT_ROLE = "Dashboard Analyst"

dashboard_agent = Agent(
    role=DASHBOARD_AGENT_ROLE,
    goal=agent_goals["dashboard_goal"],
    backstory=prompt_templates["dashboard_agent_backstory"].strip(),
    llm=_llm,
    tools=[get_period_summary, get_chart_series, get_streak_board],
    verbose=False,
)
