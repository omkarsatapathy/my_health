from crewai import Agent, LLM

from app.config import llm_config, prompt_templates, settings
from app.agents.lifestyle.tools.plan_state_tools import save_plan_answer, get_plan_state
from app.agents.lifestyle.tools.vitals_tools import save_vitals
from app.agents.lifestyle.tools.body_assessment_tools import save_body_assessment
from app.agents.lifestyle.tools.plan_doc_tools import (
    generate_plan_doc,
    save_plan_doc,
    get_plan_doc,
    patch_plan_doc,
)

_llm = LLM(
    model=f"anthropic/{llm_config['anthropic']['chat_model']}",
    api_key=settings.anthropic_api_key,
    temperature=llm_config["temperature"],
    stream=True,
)

LIFESTYLE_AGENT_ROLE = "Lifestyle Planner"

lifestyle_agent = Agent(
    role=LIFESTYLE_AGENT_ROLE,
    goal=(
        "Run a guided onboarding interview, then synthesize a single ~1500-word "
        "lifestyle plan that every other specialist reads as binding context. "
        "Edit the plan in place when the user asks; re-plan when targets are reached."
    ),
    backstory=prompt_templates["lifestyle_system_prompt"],
    llm=_llm,
    tools=[
        save_plan_answer,
        get_plan_state,
        save_vitals,
        save_body_assessment,
        generate_plan_doc,
        save_plan_doc,
        get_plan_doc,
        patch_plan_doc,
    ],
    verbose=False,
)
