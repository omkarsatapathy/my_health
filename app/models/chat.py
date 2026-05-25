from typing import Literal
from pydantic import BaseModel


class ImagePayload(BaseModel):
    mediaType: str
    encoding: Literal["base64"]
    data: str | None = None
    url: str | None = None
    s3_key: str | None = None
    vision_summary: str | None = None
    width: int | None = None
    height: int | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    image: ImagePayload | None = None
    session_id: str | None = None
    message_id: str | None = None
    created_at: str | None = None
    incomplete: bool = False


class ChatRequest(BaseModel):
    chatHistory: list[ChatMessage]
    currentMessage: ChatMessage
    user_id: str = "omkar"
    session_id: str | None = None


class ChatResponse(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str
    session_id: str | None = None


class SessionSummary(BaseModel):
    session_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    last_preview: str


class SessionDetail(BaseModel):
    session_id: str
    title: str
    messages: list[ChatMessage]
