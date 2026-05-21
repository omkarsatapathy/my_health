"""AgentCore Runtime contract: POST /invocations (streaming) + GET /ping."""
import json
import traceback

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from app.agents.orchestrator.streaming import stream_orchestrator
from app.models.chat import ChatMessage, ChatRequest
from app.observability import get_logger, user_id_var
from app.vision.processor import analyze_image, format_analysis_for_context

router = APIRouter()
log = get_logger("api.agentcore")


def _build_chat_summary(history: list[ChatMessage]) -> str:
    if not history:
        return "No prior conversation."
    return "\n".join(f"{m.role.upper()}: {m.content}" for m in history[-10:])


@router.get("/ping")
async def ping():
    return JSONResponse({"status": "Healthy"})


@router.post("/invocations")
async def invocations(request: ChatRequest):
    user_id_var.set(request.user_id or "-")
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

    if current.image:
        log.info("vision_analyze_start")
        analysis = await analyze_image(current.image)
        log.info("vision_analyze_ok", extra={"image_type": analysis.image_type})
        user_context = f"{current.content}\n\n{format_analysis_for_context(analysis)}"
    else:
        user_context = current.content
    chat_summary = _build_chat_summary(request.chatHistory)

    async def gen():
        yield ": ping\n\n"
        chunks = 0
        try:
            async for chunk in stream_orchestrator(
                request.user_id, user_context, chat_summary
            ):
                chunks += 1
                yield f'data: {{"token": {json.dumps(chunk)}}}\n\n'
            log.info("invocations_stream_done", extra={"chunks": chunks})
        except Exception as exc:
            log.exception("invocations_stream_error", extra={"error_type": type(exc).__name__})
            traceback.print_exc()
            payload = json.dumps(f"{type(exc).__name__}: {exc}")
            yield f'data: {{"error": {payload}}}\n\n'
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
