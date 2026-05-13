from crewai import Agent, LLM

from app.config import agent_goals, llm_config, prompt_templates, settings
from app.agents.physician.tools.weight_tools import (
    log_weight_entry,
    get_weight_trend,
)
from app.agents.physician.tools.health_tools import (
    calculate_bmi,
    assess_sedentary_risk,
    generate_health_report,
)

_llm = LLM(
    model=f"anthropic/{llm_config['anthropic']['chat_model']}",
    api_key=settings.anthropic_api_key,
    temperature=llm_config["temperature"],
    stream=True,
)

PHYSICIAN_AGENT_ROLE = "Physician Monitor"

physician_agent = Agent(
    role=PHYSICIAN_AGENT_ROLE,
    goal=agent_goals["physician_goal"],
    backstory=prompt_templates["physician_system_prompt"],
    llm=_llm,
    tools=[
        log_weight_entry,
        get_weight_trend,
        calculate_bmi,
        assess_sedentary_risk,
        generate_health_report,
    ],
    verbose=False,
)
