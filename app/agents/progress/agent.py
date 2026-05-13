from crewai import Agent, LLM

from app.config import llm_config, prompt_templates, settings
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
    goal=(
        "Synthesise weight, calorie balance, workout consistency, and streaks "
        "into a single progress view and compare against the stored goal. "
        "Report numbers verbatim; defer logging and motivational framing to other agents."
    ),
    backstory=prompt_templates["progress_system_prompt"],
    llm=_llm,
    tools=[
        get_metrics_snapshot,
        get_goal_progress,
    ],
    verbose=False,
)
