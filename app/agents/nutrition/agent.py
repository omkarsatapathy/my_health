from crewai import Agent, LLM

from app.config import llm_config, settings
from app.agents.nutrition.tools.meal_tools import log_meal_entry, get_daily_calorie_log
from app.agents.nutrition.tools.water_tools import log_water_intake
from app.agents.nutrition.tools.diet_tools import get_diet_schedule, generate_meal_plan
from app.agents.nutrition.tools.nutrition_tools import get_food_nutrition_facts, calculate_macro_balance

_llm = LLM(
    model=f"anthropic/{llm_config['anthropic']['chat_model']}",
    api_key=settings.anthropic_api_key,
    temperature=llm_config["temperature"],
)

nutrition_agent = Agent(
    role="Nutrition Specialist",
    goal=(
        "Track meals and water intake, analyse macros, generate Indian meal plans, "
        "and provide accurate calorie and nutrient guidance."
    ),
    backstory=(
        "You are a certified Indian dietician with deep knowledge of local ingredients "
        "available at kirana stores and vegetable markets. You help users log food, "
        "plan balanced meals within their calorie budget, and flag macro imbalances early."
    ),
    llm=_llm,
    tools=[
        log_meal_entry,
        get_daily_calorie_log,
        log_water_intake,
        get_diet_schedule,
        generate_meal_plan,
        get_food_nutrition_facts,
        calculate_macro_balance,
    ],
    verbose=False,
)
