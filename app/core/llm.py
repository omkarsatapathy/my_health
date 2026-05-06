from openai import AsyncOpenAI

from app.config import llm_config, prompt_templates, settings
from app.models.chat import ChatMessage

_client = AsyncOpenAI(api_key=settings.openai_api_key)
_system_prompt: str = prompt_templates["system_prompt"].strip()


def _build_openai_messages(history: list[ChatMessage], current: ChatMessage) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": _system_prompt}]

    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})

    if current.image:
        messages.append({
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
        })
    else:
        messages.append({"role": "user", "content": current.content})

    return messages


async def call_chat_llm(history: list[ChatMessage], current: ChatMessage) -> str:
    model = settings.openai_vision_model if current.image else settings.openai_chat_model
    messages = _build_openai_messages(history, current)

    response = await _client.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=llm_config["max_tokens"],
        temperature=llm_config["temperature"],
    )

    print("LLM Response:", response.choices[0].message.content)
    return response.choices[0].message.content
