from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.agentcore import router as agentcore_router
from app.api.routes.chat import router as chat_router
from app.config import api_config, app_config
from app.observability import (
    clear_request_context,
    get_logger,
    new_request_id,
    request_id_var,
    setup_logging,
)

setup_logging()
log = get_logger("app.main")

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


@app.middleware("http")
async def request_logger(request: Request, call_next):
    rid = request.headers.get("x-request-id") or new_request_id()
    token = request_id_var.set(rid)
    log.info(
        "http_request_start",
        extra={"method": request.method, "path": request.url.path},
    )
    try:
        response = await call_next(request)
    except Exception:
        log.exception("http_request_error", extra={"path": request.url.path})
        raise
    finally:
        log.info(
            "http_request_end",
            extra={"method": request.method, "path": request.url.path},
        )
        request_id_var.reset(token)
        clear_request_context()
    response.headers["x-request-id"] = rid
    return response


app.include_router(chat_router, prefix=api_config["prefix"])
app.include_router(agentcore_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "healthpulse-ai"}


log.info("app_ready", extra={"title": app_config["title"], "version": app_config["version"]})
