"""JSON-formatted structured logging to stdout (CloudWatch-friendly)."""
import json
import logging
import os
import sys
from datetime import datetime, timezone

from app.observability.context import request_id_var, user_id_var

_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message",
}


class JsonFormatter(logging.Formatter):
    """Render log records as one-line JSON for CloudWatch ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
            "user_id": user_id_var.get(),
        }
        for k, v in record.__dict__.items():
            if k not in _RESERVED and not k.startswith("_"):
                payload[k] = _safe(v)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _safe(v):
    try:
        json.dumps(v)
        return v
    except Exception:
        return str(v)


_configured = False


def setup_logging(level: str | None = None) -> None:
    """Install JSON handler on root logger. Idempotent."""
    global _configured
    if _configured:
        return
    log_level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)

    # Quiet noisy 3rd-party loggers
    for noisy in ("botocore", "boto3", "urllib3", "httpx", "httpcore", "openai", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).info("logging_initialized", extra={"level": log_level})


def get_logger(name: str) -> logging.LoggerAdapter | logging.Logger:
    return logging.getLogger(name)
