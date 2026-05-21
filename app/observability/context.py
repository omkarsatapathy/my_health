"""Request-scoped context for log correlation."""
import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
user_id_var: ContextVar[str] = ContextVar("user_id", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def set_request_context(request_id: str | None = None, user_id: str | None = None) -> str:
    rid = request_id or new_request_id()
    request_id_var.set(rid)
    if user_id is not None:
        user_id_var.set(user_id)
    return rid


def clear_request_context() -> None:
    request_id_var.set("-")
    user_id_var.set("-")
