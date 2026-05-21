"""Tool + function tracing decorators."""
import functools
import time

from crewai.tools import tool as _crewai_tool

from app.observability.config import get_logger


def _arg_shape(args, kwargs):
    """Cheap summary of call args — names only, no PII."""
    return {
        "kwargs": list(kwargs.keys()),
        "n_args": len(args),
    }


def traced_tool(name: str):
    """Drop-in for crewai.tools.tool that adds structured call logging."""
    log = get_logger(f"tool.{name}")

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            log.info("tool_start", extra={"tool": name, **_arg_shape(args, kwargs)})
            try:
                result = fn(*args, **kwargs)
            except Exception as e:
                dt_ms = round((time.perf_counter() - t0) * 1000, 1)
                log.exception(
                    "tool_error",
                    extra={"tool": name, "duration_ms": dt_ms, "error_type": type(e).__name__},
                )
                raise
            dt_ms = round((time.perf_counter() - t0) * 1000, 1)
            log.info("tool_ok", extra={"tool": name, "duration_ms": dt_ms})
            return result

        return _crewai_tool(name)(wrapper)

    return decorator


def traced(label: str, logger_name: str | None = None):
    """Log entry/exit/timing for a plain function (sync)."""
    log = get_logger(logger_name or f"trace.{label}")

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            log.info(f"{label}_start")
            try:
                result = fn(*args, **kwargs)
            except Exception as e:
                dt_ms = round((time.perf_counter() - t0) * 1000, 1)
                log.exception(
                    f"{label}_error",
                    extra={"duration_ms": dt_ms, "error_type": type(e).__name__},
                )
                raise
            dt_ms = round((time.perf_counter() - t0) * 1000, 1)
            log.info(f"{label}_ok", extra={"duration_ms": dt_ms})
            return result

        return wrapper

    return decorator
