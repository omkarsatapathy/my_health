from crewai import Agent, LLM

from app.config import agent_goals, llm_config, settings
from app.agents.nutrition.tools.meal_tools import log_meal_entry, get_daily_calorie_log
from app.agents.nutrition.tools.water_tools import log_water_intake
from app.agents.nutrition.tools.diet_tools import get_diet_schedule, generate_meal_plan
from app.agents.nutrition.tools.nutrition_tools import get_food_nutrition_facts, calculate_macro_balance
from app.shared.tools.web_search import web_search

_llm = LLM(
    model=f"anthropic/{llm_config['anthropic']['chat_model']}",
    api_key=settings.anthropic_api_key,
    temperature=llm_config["temperature"],
    stream=True,
)

NUTRITION_AGENT_ROLE = "Nutrition Specialist"

nutrition_agent = Agent(
    role=NUTRITION_AGENT_ROLE,
    goal=agent_goals["nutrition_goal"],
    backstory=(
        "You are a certified Indian dietician with deep knowledge of local ingredients "
        "available at kirana stores and vegetable markets. You help users log food, "
        "plan balanced meals within their calorie budget, and flag macro imbalances early.\n\n"
        "SCOPE — what you HANDLE:\n"
        "- Logging meals and water; querying single-day totals (today, yesterday, specific date) "
        "for calories, water, macros, or meal lists. Use get_daily_calorie_log for lookups.\n"
        "- Indian meal plans, food nutrition facts, macro-balance analysis, kirana-friendly suggestions.\n\n"
        "SCOPE — what you DO NOT HANDLE (defer):\n"
        "- Workouts / calories-burned → Fitness agent.\n"
        "- Weight / BMI / sedentary risk / monthly report → Physician agent.\n"
        "- Multi-day trends, plateau, goal ETA → Progress agent.\n"
        "- Streaks / motivation / reminders → Motivation agent.\n"
        "- Symptoms / first aid / supplements → Consult agent.\n"
        "- Health history / allergies / medications / goal-setting → Intake agent."
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
        web_search,
    ],
    verbose=False,
)
