from openai import AsyncOpenAI
from app.config import settings
from app.models.chat import ChatMessage

_client = AsyncOpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = (
    "You are HealthPulse AI, a personal health companion. "
    "You act as a professional dietician, gym trainer, physician monitor, and motivational coach. "
    "You help users track meals, workouts, weight, water intake, and overall wellness. "
    "For Indian users, recommend affordable ingredients available at local kirana stores and vegetable markets. "
    "Always append a medical disclaimer when answering symptom or clinical questions. "
    "Be concise, warm, and actionable."
)


def _build_openai_messages(
    history: list[ChatMessage], current: ChatMessage
) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})

    if current.image:
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": current.content},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{current.image.mediaType};{current.image.encoding},{current.image.data}"
                        },
                    },
                ],
            }
        )
    else:
        messages.append({"role": "user", "content": current.content})

    return messages


async def call_chat_llm(history: list[ChatMessage], current: ChatMessage) -> str:
    model = (
        settings.openai_vision_model
        if current.image
        else settings.openai_chat_model
    )
    messages = _build_openai_messages(history, current)

    response = await _client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=1024,
        temperature=0.7,
    )
    return response.choices[0].message.content
