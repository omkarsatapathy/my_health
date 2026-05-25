"""AgentCore Runtime contract: POST /invocations (streaming) + GET /ping."""
import asyncio
import base64
import json
import traceback

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app.agents.orchestrator.streaming import stream_orchestrator
from app.config import DEFAULT_USER_ID
from app.core.chat_store import (
    append_message,
    create_session,
    get_session,
    get_session_detail,
    new_message_id,
    update_session_title_from_first_turn,
)
from app.core.s3 import upload_image_bytes
from app.models.chat import ChatMessage, ChatRequest
from app.observability import get_logger, user_id_var
from app.vision.processor import analyze_image, format_analysis_for_context

router = APIRouter()
log = get_logger("api.agentcore")


def _build_chat_summary(history: list[ChatMessage]) -> str:
    if not history:
        return "No prior conversation."
    return "\n".join(f"{m.role.upper()}: {m.content}" for m in history[-10:])


def _resolve_user_id(request: ChatRequest) -> str:
    return request.user_id or DEFAULT_USER_ID


def _resolve_session_id(user_id: str, requested_session_id: str | None) -> str:
    if requested_session_id:
        session = get_session(user_id, requested_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return requested_session_id
    session = create_session(user_id)
    return session.session_id


async def _build_user_context_and_image(
    current: ChatMessage,
    user_id: str,
    session_id: str,
) -> tuple[str, dict | None, str | None]:
    if not current.image:
        return current.content, None, None

    message_id = new_message_id()
    raw_bytes = base64.b64decode(current.image.data or "")
    s3_key = upload_image_bytes(
        user_id=user_id,
        session_id=session_id,
        msg_id=message_id,
        media_type=current.image.mediaType,
        raw_bytes=raw_bytes,
    )

    log.info("vision_analyze_start")
    analysis = await analyze_image(current.image)
    log.info("vision_analyze_ok", extra={"image_type": analysis.image_type})
    image_context = format_analysis_for_context(analysis)
    image_payload = {
        "s3_key": s3_key,
        "media_type": current.image.mediaType,
        "vision_summary": image_context,
    }
    return f"{current.content}\n\n{image_context}", image_payload, message_id


def _maybe_schedule_title(user_id: str, session_id: str, first_user_text: str, first_assistant_text: str) -> None:
    detail = get_session_detail(user_id, session_id)
    if detail and len(detail.messages) == 2:
        asyncio.create_task(
            update_session_title_from_first_turn(
                user_id,
                session_id,
                first_user_text,
                first_assistant_text,
            )
        )


@router.get("/ping")
async def ping():
    return JSONResponse({"status": "Healthy"})


@router.post("/invocations")
async def invocations(request: ChatRequest):
    user_id = _resolve_user_id(request)
    user_id_var.set(user_id)
    try:
        current = request.currentMessage
        has_image = current.image is not None
        log.info(
            "invocations_received",
            extra={
                "has_image": has_image,
                "history_len": len(request.chatHistory),
                "msg_len": len(current.content or ""),
            },
        )

        session_id = _resolve_session_id(user_id, request.session_id)
        user_context, image_payload, image_message_id = await _build_user_context_and_image(
            current,
            user_id,
            session_id,
        )
        append_message(
            user_id,
            session_id,
            "user",
            current.content,
            image=image_payload,
            message_id=image_message_id,
        )
        chat_summary = _build_chat_summary(request.chatHistory)

        async def gen():
            yield ": ping\n\n"
            yield f"event: session\ndata: {json.dumps({'session_id': session_id})}\n\n"
            chunks = 0
            assistant_buffer = ""
            completed = False
            try:
                async for chunk in stream_orchestrator(user_id, user_context, chat_summary):
                    chunks += 1
                    assistant_buffer += chunk
                    yield f'data: {{"token": {json.dumps(chunk)}}}\n\n'
                completed = True
                if assistant_buffer:
                    append_message(user_id, session_id, "assistant", assistant_buffer)
                    _maybe_schedule_title(user_id, session_id, current.content, assistant_buffer)
                log.info("invocations_stream_done", extra={"chunks": chunks})
            except asyncio.CancelledError:
                log.info("invocations_stream_cancelled", extra={"session_id": session_id, "chunks": chunks})
                raise
            except Exception as exc:
                log.exception("invocations_stream_error", extra={"error_type": type(exc).__name__})
                traceback.print_exc()
                payload = json.dumps(f"{type(exc).__name__}: {exc}")
                yield f'data: {{"error": {payload}}}\n\n'
            finally:
                if assistant_buffer and not completed:
                    append_message(
                        user_id,
                        session_id,
                        "assistant",
                        assistant_buffer,
                        incomplete=True,
                    )
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("invocations_setup_error", extra={"error_type": type(exc).__name__})
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
