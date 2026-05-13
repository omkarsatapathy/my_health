from crewai import Agent, LLM

from app.config import agent_goals, llm_config, prompt_templates, settings
from app.agents.fitness.tools.workout_tools import (
    log_workout_session,
    get_workout_history,
)
from app.agents.fitness.tools.calorie_tools import calculate_calories_burned
from app.agents.nutrition.tools.meal_tools import get_daily_calorie_log

_llm = LLM(
    model=f"anthropic/{llm_config['anthropic']['chat_model']}",
    api_key=settings.anthropic_api_key,
    temperature=llm_config["temperature"],
    stream=True,
)

FITNESS_AGENT_ROLE = "Fitness Coach"

fitness_agent = Agent(
    role=FITNESS_AGENT_ROLE,
    goal=agent_goals["fitness_goal"],
    backstory=prompt_templates["fitness_system_prompt"],
    llm=_llm,
    tools=[
        log_workout_session,
        get_workout_history,
        calculate_calories_burned,
        get_daily_calorie_log,
    ],
    verbose=False,
)
