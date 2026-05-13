from crewai import Agent, LLM

from app.config import agent_goals, llm_config, prompt_templates, settings
from app.agents.intake.tools.history_tools import upsert_health_history
from app.agents.intake.tools.goal_tools import set_goal
from app.agents.intake.tools.constraint_tools import check_constraints

_llm = LLM(
    model=f"anthropic/{llm_config['anthropic']['chat_model']}",
    api_key=settings.anthropic_api_key,
    temperature=llm_config["temperature"],
    stream=True,
)

INTAKE_AGENT_ROLE = "Health Intake Specialist"

intake_agent = Agent(
    role=INTAKE_AGENT_ROLE,
    goal=agent_goals["intake_goal"],
    backstory=prompt_templates["intake_system_prompt"],
    llm=_llm,
    tools=[
        upsert_health_history,
        set_goal,
        check_constraints,
    ],
    verbose=False,
)
