from crewai import Agent, LLM

from app.config import llm_config, prompt_templates, settings
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
    goal=(
        "Log weight with best-practice guidance, compute BMI, track weight trends, "
        "assess sedentary risk, and generate monthly health reports. "
        "Always append a medical disclaimer for clinical or symptom queries."
    ),
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
