from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from app.config import DEFAULT_USER_ID, settings
from app.core.chat_store import delete_session, get_session, get_session_detail, list_sessions, rename_session
from app.models.chat import SessionDetail, SessionSummary
from app.observability import get_logger, user_id_var

router = APIRouter()
log = get_logger("api.sessions")


@router.get("/sessions")
async def sessions(
    user_id: str = DEFAULT_USER_ID,
    limit: Annotated[int, Query(ge=1, le=100)] = settings.session_list_page_size,
    cursor: str | None = None,
):
    user_id_var.set(user_id or DEFAULT_USER_ID)
    items, next_cursor = list_sessions(user_id, limit=limit, cursor=cursor)
    return {"sessions": [item.model_dump() for item in items], "next_cursor": next_cursor}


@router.get("/sessions/{session_id}/messages", response_model=SessionDetail)
async def session_messages(session_id: str, user_id: str = DEFAULT_USER_ID) -> SessionDetail:
    user_id_var.set(user_id or DEFAULT_USER_ID)
    detail = get_session_detail(user_id, session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


@router.patch("/sessions/{session_id}", response_model=SessionSummary)
async def session_rename(session_id: str, payload: dict, user_id: str = DEFAULT_USER_ID) -> SessionSummary:
    user_id_var.set(user_id or DEFAULT_USER_ID)
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    summary = rename_session(user_id, session_id, title)
    if not summary:
        raise HTTPException(status_code=404, detail="Session not found")
    return summary


@router.delete("/sessions/{session_id}", status_code=204)
async def session_delete(session_id: str, user_id: str = DEFAULT_USER_ID) -> Response:
    user_id_var.set(user_id or DEFAULT_USER_ID)
    if not get_session(user_id, session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    deleted_messages, deleted_s3 = delete_session(user_id, session_id)
    log.info(
        "session_delete_api",
        extra={"session_id": session_id, "deleted_messages": deleted_messages, "deleted_s3": deleted_s3},
    )
    return Response(status_code=204)