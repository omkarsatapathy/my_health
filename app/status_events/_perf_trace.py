# === TEMP PERF TRACE — DELETE BEFORE DEPLOY ===
# Writes one JSONL line per status event with monotonic + wall timestamps.
# Enable with: MYHEALTH_PERF_TRACE=1
# Output:      /tmp/myhealth_perf_trace.jsonl
# Remove:      delete this file + the import/call in emitter.py (grep "TEMP PERF TRACE")
import json
import os
import threading
import time
from typing import Any

_ENABLED = os.environ.get("MYHEALTH_PERF_TRACE") == "1"
_PATH = "/tmp/myhealth_perf_trace.jsonl"
_lock = threading.Lock()
_t0 = time.monotonic()


def enabled() -> bool:
    return _ENABLED


def record(payload: dict[str, Any]) -> None:
    if not _ENABLED:
        return
    now = time.monotonic()
    line = {
        "t_mono": round(now - _t0, 6),
        "t_wall": time.time(),
        "tid": threading.get_ident(),
        "kind": payload.get("kind"),
        "agent": payload.get("agent"),
        "label": payload.get("label"),
    }
    try:
        with _lock, open(_PATH, "a") as f:
            f.write(json.dumps(line) + "\n")
    except Exception:
        pass
# === END TEMP PERF TRACE ===
