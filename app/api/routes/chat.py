import json
import traceback

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.agents.orchestrator.agent import run_orchestrator
from app.agents.orchestrator.streaming import stream_orchestrator
from app.models.chat import ChatMessage, ChatRequest, ChatResponse
from app.observability import get_logger, user_id_var
from app.vision.processor import analyze_image, format_analysis_for_context

router = APIRouter()
log = get_logger("api.chat")


def _build_chat_summary(history: list[ChatMessage]) -> str:
    """Condense chat history into a plain-text summary for the orchestrator."""
    if not history:
        return "No prior conversation."
    lines = [f"{msg.role.upper()}: {msg.content}" for msg in history[-10:]]
    return "\n".join(lines)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    user_id_var.set(request.user_id or "-")
    try:
        current = request.currentMessage
        has_image = current.image is not None
        log.info(
            "chat_received",
            extra={"has_image": has_image, "history_len": len(request.chatHistory)},
        )
        user_text = current.content

        if current.image:
            log.info("vision_analyze_start")
            analysis = await analyze_image(current.image)
            log.info("vision_analyze_ok", extra={"image_type": analysis.image_type})
            image_context = format_analysis_for_context(analysis)
            user_context = f"{user_text}\n\n{image_context}"
        else:
            user_context = user_text

        chat_summary = _build_chat_summary(request.chatHistory)
        reply = await run_orchestrator(request.user_id, user_context, chat_summary)
        log.info("chat_ok", extra={"reply_len": len(reply or "")})

        return ChatResponse(content=reply)

    except Exception as e:
        log.exception("chat_error", extra={"error_type": type(e).__name__})
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """SSE endpoint — runs orchestrator (with tools) then streams the reply token-by-token."""
    user_id_var.set(request.user_id or "-")
    try:
        current = request.currentMessage
        has_image = current.image is not None
        log.info(
            "chat_stream_received",
            extra={"has_image": has_image, "history_len": len(request.chatHistory)},
        )
        user_text = current.content

        if current.image:
            log.info("vision_analyze_start")
            analysis = await analyze_image(current.image)
            log.info("vision_analyze_ok", extra={"image_type": analysis.image_type})
            image_context = format_analysis_for_context(analysis)
            user_context = f"{user_text}\n\n{image_context}"
        else:
            user_context = user_text

        chat_summary = _build_chat_summary(request.chatHistory)

        async def _orch_stream():
            yield ": ping\n\n"
            chunks = 0
            try:
                async for chunk in stream_orchestrator(
                    request.user_id, user_context, chat_summary
                ):
                    chunks += 1
                    yield f'data: {{"token": {json.dumps(chunk)}}}\n\n'
                log.info("chat_stream_done", extra={"chunks": chunks})
            except Exception as exc:
                log.exception("chat_stream_error", extra={"error_type": type(exc).__name__})
                traceback.print_exc()
                payload = json.dumps(f"{type(exc).__name__}: {exc}")
                yield f'data: {{"error": {payload}}}\n\n'
            finally:
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            _orch_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    except Exception as e:
        log.exception("chat_stream_setup_error", extra={"error_type": type(e).__name__})
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
