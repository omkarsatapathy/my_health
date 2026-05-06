from fastapi import APIRouter, HTTPException
from app.models.chat import ChatRequest, ChatResponse
from app.core.llm import call_chat_llm

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        reply = await call_chat_llm(request.chatHistory, request.currentMessage)
        return ChatResponse(content=reply)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
