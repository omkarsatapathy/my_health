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
from app.status_events import bind as bind_status, unbind as unbind_status
from app.status_events import pipeline as status_pipeline
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

    loop = asyncio.get_running_loop()
    status_queue: asyncio.Queue = asyncio.Queue()
    bind_status(loop, status_queue)

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
        status_pipeline("Starting up")

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
            # Rebind inside the streaming task so this task's context sees the status sink.
            bind_status(loop, status_queue)

            yield ": ping\n\n"
            yield f"event: session\ndata: {json.dumps({'session_id': session_id})}\n\n"

            # Flush status events queued during the setup phase (vision, "Starting up", etc.)
            while not status_queue.empty():
                ev = status_queue.get_nowait()
                yield f"event: status\ndata: {json.dumps(ev)}\n\n"

            chunks = 0
            assistant_buffer = ""
            completed = False
            try:
                # Race the next chunk against the next status event so statuses
                # reach the client in real time, not buffered until the first token.
                # Otherwise "Classifying intent / Loading meals / …" pile up while
                # the orchestrator is thinking and only flush in a burst right
                # before tokens — making the last setup status (e.g. "Saving chat")
                # appear to hang on screen during the entire wait.
                chunks_iter = stream_orchestrator(user_id, user_context, chat_summary).__aiter__()
                chunk_task: asyncio.Task | None = asyncio.create_task(chunks_iter.__anext__())
                status_task: asyncio.Task | None = asyncio.create_task(status_queue.get())
                while chunk_task is not None:
                    done, _ = await asyncio.wait(
                        {chunk_task, status_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if status_task in done:
                        ev = status_task.result()
                        yield f"event: status\ndata: {json.dumps(ev)}\n\n"
                        status_task = asyncio.create_task(status_queue.get())
                    if chunk_task in done:
                        try:
                            chunk = chunk_task.result()
                        except StopAsyncIteration:
                            chunk_task = None
                            break
                        chunks += 1
                        assistant_buffer += chunk
                        yield f'data: {{"token": {json.dumps(chunk)}}}\n\n'
                        chunk_task = asyncio.create_task(chunks_iter.__anext__())
                status_task.cancel()
                completed = True
                # Final drain (tool/db events that landed after the last token)
                while not status_queue.empty():
                    ev = status_queue.get_nowait()
                    yield f"event: status\ndata: {json.dumps(ev)}\n\n"
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
                unbind_status()
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except HTTPException:
        unbind_status()
        raise
    except Exception as exc:
        unbind_status()
        log.exception("invocations_setup_error", extra={"error_type": type(exc).__name__})
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
