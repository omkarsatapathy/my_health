from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.chat import router as chat_router
from app.config import api_config, app_config

app = FastAPI(
    title=app_config["title"],
    description=app_config["description"],
    version=app_config["version"],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_config["cors_origins"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix=api_config["prefix"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "healthpulse-ai"}
