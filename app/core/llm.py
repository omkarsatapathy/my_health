import time

import anthropic
from openai import AsyncOpenAI

from app.config import llm_config, llm_provider, prompt_templates, settings
from app.models.chat import ChatMessage
from app.observability import get_logger

log = get_logger("core.llm")

_system_prompt: str = prompt_templates["system_prompt"].strip()

_openai_client: AsyncOpenAI | None = None
_anthropic_client: anthropic.AsyncAnthropic | None = None


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


def _get_anthropic_client() -> anthropic.AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


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


def _build_anthropic_messages(history: list[ChatMessage], current: ChatMessage) -> list[dict]:
    messages: list[dict] = []

    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})

    if current.image:
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": current.image.mediaType,
                        "data": current.image.data,
                    },
                },
                {"type": "text", "text": current.content},
            ],
        })
    else:
        messages.append({"role": "user", "content": current.content})

    return messages


async def _call_openai(history: list[ChatMessage], current: ChatMessage) -> str:
    model = settings.vision_model if current.image else settings.chat_model
    messages = _build_openai_messages(history, current)
    log.info("llm_call_start", extra={"provider": "openai", "model": model, "n_messages": len(messages)})
    t0 = time.perf_counter()
    try:
        response = await _get_openai_client().chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=llm_config["max_tokens"],
            temperature=llm_config["temperature"],
        )
    except Exception as e:
        log.exception("llm_call_error", extra={"provider": "openai", "model": model, "error_type": type(e).__name__})
        raise
    dt = round((time.perf_counter() - t0) * 1000, 1)
    usage = getattr(response, "usage", None)
    log.info(
        "llm_call_ok",
        extra={
            "provider": "openai",
            "model": model,
            "duration_ms": dt,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        },
    )
    return response.choices[0].message.content


async def _call_anthropic(history: list[ChatMessage], current: ChatMessage) -> str:
    model = settings.vision_model if current.image else settings.chat_model
    messages = _build_anthropic_messages(history, current)
    log.info("llm_call_start", extra={"provider": "anthropic", "model": model, "n_messages": len(messages)})
    t0 = time.perf_counter()
    try:
        response = await _get_anthropic_client().messages.create(
            model=model,
            system=_system_prompt,
            messages=messages,
            max_tokens=llm_config["max_tokens"],
            temperature=llm_config["temperature"],
        )
    except Exception as e:
        log.exception("llm_call_error", extra={"provider": "anthropic", "model": model, "error_type": type(e).__name__})
        raise
    dt = round((time.perf_counter() - t0) * 1000, 1)
    usage = getattr(response, "usage", None)
    log.info(
        "llm_call_ok",
        extra={
            "provider": "anthropic",
            "model": model,
            "duration_ms": dt,
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        },
    )
    return response.content[0].text


async def call_chat_llm(history: list[ChatMessage], current: ChatMessage) -> str:
    if llm_provider == "anthropic":
        return await _call_anthropic(history, current)
    return await _call_openai(history, current)
