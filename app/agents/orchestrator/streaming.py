import asyncio
import threading
from functools import partial
from typing import AsyncGenerator

from crewai.events import crewai_event_bus
from crewai.events.types.llm_events import LLMStreamChunkEvent

from app.agents.nutrition.agent import NUTRITION_AGENT_ROLE
from app.agents.fitness.agent import FITNESS_AGENT_ROLE
from app.agents.physician.agent import PHYSICIAN_AGENT_ROLE
from app.agents.motivation.agent import MOTIVATION_AGENT_ROLE
from app.agents.consult.agent import CONSULT_AGENT_ROLE
from app.agents.dashboard.agent import DASHBOARD_AGENT_ROLE
from app.agents.intake.agent import INTAKE_AGENT_ROLE
from app.agents.lifestyle.agent import LIFESTYLE_AGENT_ROLE
from app.agents.orchestrator.agent import _run_orchestrator
from app.observability import get_logger

log = get_logger("orchestrator.streaming")

_SPECIALIST_ROLES = {
    NUTRITION_AGENT_ROLE,
    FITNESS_AGENT_ROLE,
    PHYSICIAN_AGENT_ROLE,
    MOTIVATION_AGENT_ROLE,
    CONSULT_AGENT_ROLE,
    DASHBOARD_AGENT_ROLE,
    INTAKE_AGENT_ROLE,
    LIFESTYLE_AGENT_ROLE,
}

_FINAL_MARKER = "Final Answer:"

# thread_id -> dict with keys: loop, queue, buffer, emitting, last_call_id
_sinks: dict[int, dict] = {}
_sinks_lock = threading.Lock()
_DONE = object()


def _push(sink: dict, text: str) -> None:
    if text:
        sink["loop"].call_soon_threadsafe(sink["queue"].put_nowait, text)


def _normalize_final_output(text: str) -> str:
    if not text:
        return ""
    idx = text.find(_FINAL_MARKER)
    if idx != -1:
        return text[idx + len(_FINAL_MARKER):].lstrip("\n").lstrip()
    return text.strip()


def _on_chunk(_source, event: LLMStreamChunkEvent) -> None:
    if event.tool_call is not None or not event.chunk:
        return
    if getattr(event, "agent_role", None) not in _SPECIALIST_ROLES:
        return
    with _sinks_lock:
        sink = _sinks.get(threading.get_ident())
    if sink is None or not isinstance(sink, dict):
        return

    call_id = getattr(event, "call_id", None) or id(event)
    if sink.get("last_call_id") != call_id and not sink.get("emitting"):
        sink["buffer"] = ""
    sink["last_call_id"] = call_id

    if sink.get("emitting"):
        _push(sink, event.chunk)
        return

    sink["buffer"] = sink.get("buffer", "") + event.chunk
    idx = sink["buffer"].find(_FINAL_MARKER)
    if idx == -1:
        if len(sink["buffer"]) > 4096:
            sink["buffer"] = sink["buffer"][-len(_FINAL_MARKER):]
        return

    tail = sink["buffer"][idx + len(_FINAL_MARKER):].lstrip("\n").lstrip()
    sink["emitting"] = True
    sink["buffer"] = ""
    _push(sink, tail)


# Prune any stale _on_chunk left behind by uvicorn --reload before registering
# the fresh one. CrewAI's bus has no public unregister API, so we mutate the
# internal frozenset.
def _prune_stale_handlers() -> None:
    existing = crewai_event_bus._sync_handlers.get(LLMStreamChunkEvent, frozenset())
    keep = frozenset(
        h for h in existing
        if not (
            getattr(h, "__module__", "") == __name__
            and getattr(h, "__qualname__", "") == "_on_chunk"
        )
    )
    if keep != existing:
        crewai_event_bus._sync_handlers[LLMStreamChunkEvent] = keep
        crewai_event_bus._execution_plan_cache.pop(LLMStreamChunkEvent, None)


_prune_stale_handlers()
crewai_event_bus.on(LLMStreamChunkEvent)(_on_chunk)


def _run_with_sink(loop, queue, user_id, user_context, chat_summary):
    tid = threading.get_ident()
    sink = {
        "loop": loop,
        "queue": queue,
        "buffer": "",
        "emitting": False,
        "last_call_id": None,
    }
    with _sinks_lock:
        _sinks[tid] = sink
    try:
        result = _run_orchestrator(user_id, user_context, chat_summary)
        if not sink["emitting"]:
            log.info("stream_fallback_emit", extra={"reply_len": len(result or "")})
            _push(sink, _normalize_final_output(result))
        return result
    except Exception:
        log.exception("stream_orchestrator_error")
        raise
    finally:
        with _sinks_lock:
            _sinks.pop(tid, None)
        loop.call_soon_threadsafe(queue.put_nowait, _DONE)


async def stream_orchestrator(
    user_id: str, user_context: str, chat_summary: str
) -> AsyncGenerator[str, None]:
    """Yield response tokens from the nutrition agent as the LLM emits them."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    fut = loop.run_in_executor(
        None,
        partial(_run_with_sink, loop, queue, user_id, user_context, chat_summary),
    )

    try:
        while True:
            item = await queue.get()
            if item is _DONE:
                break
            yield item
    finally:
        await fut
