import asyncio
import threading
from functools import partial
from typing import AsyncGenerator

from crewai.events import crewai_event_bus
from crewai.events.types.llm_events import LLMStreamChunkEvent

from app.agents.consult.agent import CONSULT_AGENT_ROLE
from app.agents.dashboard.agent import DASHBOARD_AGENT_ROLE
from app.agents.fitness.agent import FITNESS_AGENT_ROLE
from app.agents.intake.agent import INTAKE_AGENT_ROLE
from app.agents.lifestyle.agent import LIFESTYLE_AGENT_ROLE
from app.agents.motivation.agent import MOTIVATION_AGENT_ROLE
from app.agents.nutrition.agent import NUTRITION_AGENT_ROLE
from app.agents.physician.agent import PHYSICIAN_AGENT_ROLE
from app.agents.orchestrator import nutrition_fastpath
from app.agents.orchestrator.agent import _get_plan_block, _run_fast_path
from app.agents.orchestrator.planning.dispatcher import execute_plan
from app.agents.orchestrator.planning.executor import should_use_planner
from app.agents.orchestrator.planning.planner import build_plan
from app.agents.orchestrator.planning.synthesizer import SYNTHESIZER_AGENT_ROLE, synthesize
from app.agents.orchestrator.tools.intent_tools import _classify_intent, _load_user_context
from app.observability import get_logger
from app.status_events import orchestrator as status_orchestrator
from app.status_events import submit as status_submit
from app.status_events import synthesizer as status_synth

log = get_logger("orchestrator.streaming")

_SPECIALIST_ROLES = frozenset({
    NUTRITION_AGENT_ROLE,
    FITNESS_AGENT_ROLE,
    PHYSICIAN_AGENT_ROLE,
    MOTIVATION_AGENT_ROLE,
    CONSULT_AGENT_ROLE,
    DASHBOARD_AGENT_ROLE,
    INTAKE_AGENT_ROLE,
    LIFESTYLE_AGENT_ROLE,
})
_PLANNER_STREAMING_ROLES = frozenset({SYNTHESIZER_AGENT_ROLE})

_FINAL_MARKER = "Final Answer:"

# thread_id -> sink dict: loop, queue, buffer, emitting, last_call_id, allowed_roles
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
    role = getattr(event, "agent_role", None)
    with _sinks_lock:
        sink = _sinks.get(threading.get_ident())
    if sink is None or not isinstance(sink, dict):
        return
    allowed = sink.get("allowed_roles") or _SPECIALIST_ROLES
    if role not in allowed:
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


def _new_sink(loop, queue, allowed_roles: frozenset) -> dict:
    return {
        "loop": loop,
        "queue": queue,
        "buffer": "",
        "emitting": False,
        "last_call_id": None,
        "allowed_roles": allowed_roles,
    }


def _run_fast_with_sink(loop, queue, user_id, user_context, chat_summary, intent):
    tid = threading.get_ident()
    sink = _new_sink(loop, queue, _SPECIALIST_ROLES)
    with _sinks_lock:
        _sinks[tid] = sink
    try:
        if nutrition_fastpath.can_handle(intent):
            log.info("stream_route_fastfast", extra={"intent": intent})
            try:
                result = nutrition_fastpath.run(user_id, user_context)
            except Exception:
                log.exception("nutrition_fastpath_failed_falling_back")
                result = None
            if result:
                _push(sink, result)
                return result
            log.info("nutrition_fastpath_fallback_to_crewai", extra={"intent": intent})
        result = _run_fast_path(user_id, user_context, chat_summary, intent)
        if not sink["emitting"]:
            log.info("stream_fast_fallback_emit", extra={"reply_len": len(result or "")})
            _push(sink, _normalize_final_output(result))
        return result
    except Exception:
        log.exception("stream_fast_error")
        raise
    finally:
        with _sinks_lock:
            _sinks.pop(tid, None)
        loop.call_soon_threadsafe(queue.put_nowait, _DONE)


def _run_planner_with_sink(loop, queue, user_id, user_context, chat_summary, ctx, plan_summary):
    tid = threading.get_ident()
    sink = _new_sink(loop, queue, _PLANNER_STREAMING_ROLES)
    with _sinks_lock:
        _sinks[tid] = sink
    try:
        plan = build_plan(
            message=user_context,
            user_id=user_id,
            user_context=ctx,
            chat_summary=chat_summary,
            plan_summary=plan_summary,
        )
        results = asyncio.run(execute_plan(plan, user_id))
        status_synth("Composing reply")
        result = synthesize(user_context, results)
        if not sink["emitting"]:
            log.info("stream_planner_fallback_emit", extra={"reply_len": len(result or "")})
            _push(sink, _normalize_final_output(result))
        return result
    except Exception:
        log.exception("stream_planner_error")
        # Fall back to fast path silently — last-resort safety net.
        try:
            sink["allowed_roles"] = _SPECIALIST_ROLES
            intent = "ask_advice"
            result = _run_fast_path(user_id, user_context, chat_summary, intent)
            if not sink["emitting"]:
                _push(sink, _normalize_final_output(result))
            return result
        except Exception:
            log.exception("stream_planner_fallback_failed")
            raise
    finally:
        with _sinks_lock:
            _sinks.pop(tid, None)
        loop.call_soon_threadsafe(queue.put_nowait, _DONE)


async def stream_orchestrator(
    user_id: str, user_context: str, chat_summary: str
) -> AsyncGenerator[str, None]:
    """SSE stream — chooses planner or fast path, then streams the user-facing reply tokens."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    status_orchestrator("Classifying intent")
    intent_result = await status_submit(loop, _classify_intent, user_context)
    intent = intent_result.get("intent", "unknown")
    log.info(
        "stream_intent_classified",
        extra={"intent": intent, "confidence": intent_result.get("confidence")},
    )

    if should_use_planner(user_context, intent_result):
        log.info("stream_route", extra={"path": "planner"})
        status_orchestrator("Building plan")
        ctx = await status_submit(loop, _load_user_context, user_id)
        plan_summary, _ = await status_submit(loop, _get_plan_block, user_id)
        fut = status_submit(
            loop,
            partial(
                _run_planner_with_sink, loop, queue, user_id, user_context,
                chat_summary, ctx, plan_summary,
            ),
        )
    else:
        log.info("stream_route", extra={"path": "fast", "intent": intent})
        status_orchestrator("Fast routing")
        fut = status_submit(
            loop,
            partial(
                _run_fast_with_sink, loop, queue, user_id, user_context,
                chat_summary, intent,
            ),
        )

    try:
        while True:
            item = await queue.get()
            if item is _DONE:
                break
            yield item
    finally:
        await fut
