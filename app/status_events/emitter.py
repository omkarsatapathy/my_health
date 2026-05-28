"""One-line status emitter — push short, Claude-style activity pings to the SSE stream."""
import asyncio
import contextvars
import logging
import threading
from contextvars import ContextVar
from typing import Any

log = logging.getLogger("status_events")

# Per-task binding (asyncio + run_in_executor inherit this via copy_context).
_emitter_var: ContextVar[dict | None] = ContextVar("status_emitter", default=None)

# Thread-id fallback for crewai / library-spawned threads that don't inherit context.
_thread_emitters: dict[int, dict] = {}
_thread_lock = threading.Lock()


def _current() -> dict | None:
    em = _emitter_var.get()
    if em is not None:
        return em
    with _thread_lock:
        return _thread_emitters.get(threading.get_ident())


def bind(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
    """Bind a status sink for the current async + thread context."""
    emitter = {"loop": loop, "queue": queue}
    _emitter_var.set(emitter)
    with _thread_lock:
        _thread_emitters[threading.get_ident()] = emitter


def unbind() -> None:
    _emitter_var.set(None)
    with _thread_lock:
        _thread_emitters.pop(threading.get_ident(), None)


def is_bound() -> bool:
    return _current() is not None


def submit(loop: asyncio.AbstractEventLoop, func, *args):
    """run_in_executor variant that propagates the caller's contextvars (incl. status sink)."""
    ctx = contextvars.copy_context()
    return loop.run_in_executor(None, ctx.run, func, *args)


def _push(payload: dict[str, Any]) -> None:
    em = _current()
    if em is None:
        return
    try:
        em["loop"].call_soon_threadsafe(em["queue"].put_nowait, payload)
    except Exception:
        log.debug("status_emit_failed", extra={"kind": payload.get("kind")})


def emit(label: str, kind: str = "info", agent: str | None = None) -> None:
    """Emit a short status event. No-op if no sink bound."""
    if not label:
        return
    payload: dict[str, Any] = {"label": label[:48], "kind": kind}
    if agent:
        payload["agent"] = agent
    _push(payload)


# Semantic helpers — keep call sites to one line.
def pipeline(label: str) -> None:
    emit(label, kind="pipeline")


def vision(label: str) -> None:
    emit(label, kind="vision")


def orchestrator(label: str) -> None:
    emit(label, kind="orchestrator", agent="Orchestrator")


def agent(name: str, label: str | None = None) -> None:
    emit(label or name, kind="agent", agent=name)


def tool(name: str, label: str | None = None) -> None:
    emit(label or name, kind="tool", agent=name)


def db(label: str) -> None:
    emit(label, kind="db")


def synthesizer(label: str) -> None:
    emit(label, kind="synthesizer", agent="Synthesizer")
