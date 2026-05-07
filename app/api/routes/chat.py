from fastapi import APIRouter, HTTPException

from app.agents.orchestrator.agent import run_orchestrator
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

        # --- Vision stage: translate image → structured context ---
        if current.image:
            analysis = await analyze_image(current.image)
            image_context = format_analysis_for_context(analysis)
            user_context = f"{user_text}\n\n{image_context}"
        else:
            user_context = user_text

        # --- Orchestrator stage ---
        chat_summary = _build_chat_summary(request.chatHistory)
        reply = await run_orchestrator(user_context, chat_summary)

        return ChatResponse(content=reply)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
