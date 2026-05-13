from crewai import Agent, LLM

from app.config import agent_goals, llm_config, prompt_templates, settings
from app.agents.progress.tools.snapshot_tools import get_metrics_snapshot
from app.agents.progress.tools.goal_progress_tools import get_goal_progress

_llm = LLM(
    model=f"anthropic/{llm_config['anthropic']['chat_model']}",
    api_key=settings.anthropic_api_key,
    temperature=llm_config["temperature"],
    stream=True,
)

PROGRESS_AGENT_ROLE = "Progress Analyst"

progress_agent = Agent(
    role=PROGRESS_AGENT_ROLE,
    goal=agent_goals["progress_goal"],
    backstory=prompt_templates["progress_system_prompt"],
    llm=_llm,
    tools=[
        get_metrics_snapshot,
        get_goal_progress,
    ],
    verbose=False,
)
