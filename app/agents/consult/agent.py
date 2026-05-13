from crewai import Agent, LLM

from app.config import agent_goals, llm_config, prompt_templates, settings
from app.shared.tools.web_search import web_search

_llm = LLM(
    model=f"anthropic/{llm_config['anthropic']['orchestrator_model']}",
    api_key=settings.anthropic_api_key,
    temperature=llm_config["temperature"],
    stream=True,
)

CONSULT_AGENT_ROLE = "Health Consultant"

consult_agent = Agent(
    role=CONSULT_AGENT_ROLE,
    goal=agent_goals["consult_goal"],
    backstory=prompt_templates["consult_agent_backstory"].strip(),
    llm=_llm,
    tools=[web_search],
    verbose=False,
)
