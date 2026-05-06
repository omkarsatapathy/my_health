from typing import Literal
from pydantic import BaseModel


class ImagePayload(BaseModel):
    mediaType: str
    encoding: Literal["base64"]
    data: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    image: ImagePayload | None = None


class ChatRequest(BaseModel):
    chatHistory: list[ChatMessage]
    currentMessage: ChatMessage


class ChatResponse(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str
