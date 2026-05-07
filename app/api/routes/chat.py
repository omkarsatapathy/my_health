from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.agents.orchestrator.agent import run_orchestrator
from app.core.streaming import stream_chat
from app.models.chat import ChatMessage, ChatRequest, ChatResponse
from app.vision.processor import analyze_image, format_analysis_for_context

router = APIRouter()


def _build_chat_summary(history: list[ChatMessage]) -> str:
    """Condense chat history into a plain-text summary for the orchestrator."""
    if not history:
        return "No prior conversation."
    lines = [f"{msg.role.upper()}: {msg.content}" for msg in history[-10:]]
    return "\n".join(lines)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        current = request.currentMessage
        user_text = current.content

        if current.image:
            analysis = await analyze_image(current.image)
            image_context = format_analysis_for_context(analysis)
            user_context = f"{user_text}\n\n{image_context}"
        else:
            user_context = user_text

        chat_summary = _build_chat_summary(request.chatHistory)
        reply = await run_orchestrator(user_context, chat_summary)

        return ChatResponse(content=reply)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """SSE endpoint — streams tokens as `data: {"token": "..."}` events."""
    try:
        current = request.currentMessage

        # Vision stage: resolve image to text context before streaming
        if current.image:
            analysis = await analyze_image(current.image)
            image_context = format_analysis_for_context(analysis)
            enriched_content = f"{current.content}\n\n{image_context}"
            current = ChatMessage(
                role=current.role,
                content=enriched_content,
                image=current.image,
            )

        return StreamingResponse(
            stream_chat(request.chatHistory, current),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
