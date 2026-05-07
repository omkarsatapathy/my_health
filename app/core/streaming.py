import json
from typing import AsyncGenerator

from app.config import llm_config, llm_provider, settings
from app.core.llm import (
    _build_anthropic_messages,
    _build_openai_messages,
    _get_anthropic_client,
    _get_openai_client,
    _system_prompt,
)
from app.models.chat import ChatMessage


def _sse(data: str) -> str:
    return f"data: {data}\n\n"


async def stream_anthropic(
    messages: list[dict], model: str
) -> AsyncGenerator[str, None]:
    """Stream Anthropic response as SSE tokens."""
    async with _get_anthropic_client().messages.stream(
        model=model,
        system=_system_prompt,
        messages=messages,
        max_tokens=llm_config["max_tokens"],
        temperature=llm_config["temperature"],
    ) as stream:
        async for text in stream.text_stream:
            yield _sse(json.dumps({"token": text}))
    yield _sse("[DONE]")


async def stream_openai(
    messages: list[dict], model: str
) -> AsyncGenerator[str, None]:
    """Stream OpenAI response as SSE tokens."""
    stream = await _get_openai_client().chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=llm_config["max_tokens"],
        temperature=llm_config["temperature"],
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield _sse(json.dumps({"token": delta}))
    yield _sse("[DONE]")


async def stream_chat(
    history: list[ChatMessage], current: ChatMessage
) -> AsyncGenerator[str, None]:
    """Entry point: stream tokens from the configured LLM provider."""
    if llm_provider == "anthropic":
        model = settings.vision_model if current.image else settings.chat_model
        messages = _build_anthropic_messages(history, current)
        async for chunk in stream_anthropic(messages, model):
            yield chunk
    else:
        model = settings.vision_model if current.image else settings.chat_model
        messages = _build_openai_messages(history, current)
        async for chunk in stream_openai(messages, model):
            yield chunk
