import os
import threading
import time

import boto3
from boto3.dynamodb.conditions import Key

from app.config import settings
from app.observability import get_logger
from app.status_events import db as status_db

# Friendly noun for each SK prefix. Keep these short — the iOS status pill truncates
# at 48 chars but visually anything past ~28 wraps awkwardly.
_SK_NOUNS = {
    "MEAL":      "meals",
    "WORKOUT":   "workouts",
    "WATER":     "hydration",
    "WEIGHT":    "weight",
    "INTAKE":    "nutrition",
    "LIFESTYLE": "lifestyle",
    "PROFILE":   "profile",
    "MEMORY":    "memory",
    "STREAK":    "streak",
    "CHALLENGE": "challenge",
    "PLAN":      "plan",
    "HISTORY":   "history",
    "GOAL":      "goal",
    "STATE":     "state",
}

# Prefixes that are pure persistence plumbing — we don't surface them to the user.
# Chat header/message writes happen on every turn but say nothing about what the
# assistant is *thinking*; they only add noise to the status pill.
_SILENT_PREFIXES = frozenset({"CHATHDR", "CHATMSG"})

# Per-op verb. `query_sk_prefix` is plural-ish ("Loading"), `get_item` is singular
# ("Reading"). Writes/updates are uniform.
_OP_VERBS = {
    "query_sk_prefix": "Loading",
    "get_item":        "Reading",
    "put_item":        "Saving",
    "update_item":     "Updating",
}


def _label_for(op: str, sk: str) -> str | None:
    """Build a human label like 'Saving meal' from the SK prefix + op.

    Returns None for silent prefixes (chat plumbing) — caller should skip emission.
    """
    prefix = (sk or "").split("#", 1)[0].upper()
    if prefix in _SILENT_PREFIXES:
        return None
    noun = _SK_NOUNS.get(prefix)
    verb = _OP_VERBS.get(op, "Accessing")
    if noun:
        return f"{verb} {noun}"
    return f"{verb} data"


# Per-thread last-emitted label so consecutive identical DB pings collapse into
# one status update instead of spamming the pill (e.g. five MEAL reads in a row).
_last_label: dict[int, str] = {}
_last_label_lock = threading.Lock()


def _emit_dedup(label: str) -> None:
    tid = threading.get_ident()
    with _last_label_lock:
        prev = _last_label.get(tid)
        if prev == label:
            return
        _last_label[tid] = label
    status_db(label)

log = get_logger("core.db")

# Only set AWS_PROFILE when running outside AWS (locally). Inside a Lambda /
# AgentCore container, the SDK uses the attached IAM role automatically.
if not os.environ.get("AWS_EXECUTION_ENV") and not os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"):
    os.environ.setdefault("AWS_PROFILE", settings.aws_profile)

_dynamodb = None
_table = None


def get_table():
    """Return singleton DynamoDB table resource."""
    global _dynamodb, _table
    if _table is None:
        _dynamodb = boto3.resource(
            "dynamodb",
            region_name=settings.aws_region,
        )
        _table = _dynamodb.Table(settings.dynamodb_table)
    return _table


def _timed(op: str, sk: str, fn):
    label = _label_for(op, sk)
    if label is not None:
        _emit_dedup(label)
    t0 = time.perf_counter()
    try:
        out = fn()
    except Exception as e:
        dt = round((time.perf_counter() - t0) * 1000, 1)
        log.exception("db_error", extra={"op": op, "sk": sk, "duration_ms": dt, "error_type": type(e).__name__})
        raise
    dt = round((time.perf_counter() - t0) * 1000, 1)
    log.info("db_ok", extra={"op": op, "sk": sk, "duration_ms": dt})
    return out


def query_sk_prefix(user_id: str, sk_prefix: str) -> list[dict]:
    """Query all items for a user where SK begins with sk_prefix."""
    table = get_table()

    def _run():
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{user_id}") & Key("sk").begins_with(sk_prefix)
        )
        return resp.get("Items", [])

    items = _timed("query_sk_prefix", sk_prefix, _run)
    log.info("db_query_count", extra={"op": "query_sk_prefix", "sk": sk_prefix, "count": len(items)})
    return items


def put_item(user_id: str, sk: str, data: dict) -> None:
    """Write a single item; pk and sk are injected automatically."""
    table = get_table()
    _timed("put_item", sk, lambda: table.put_item(Item={"pk": f"USER#{user_id}", "sk": sk, **data}))


def get_item(user_id: str, sk: str) -> dict | None:
    """Fetch a single item by exact pk + sk."""
    table = get_table()
    resp = _timed("get_item", sk, lambda: table.get_item(Key={"pk": f"USER#{user_id}", "sk": sk}))
    return resp.get("Item")


def update_item(user_id: str, sk: str, fields: dict) -> dict:
    """Partially update an item's fields."""
    table = get_table()
    expr = "SET " + ", ".join(f"#f{i} = :v{i}" for i in range(len(fields)))
    names = {f"#f{i}": k for i, k in enumerate(fields)}
    values = {f":v{i}": v for i, v in enumerate(fields.values())}

    def _run():
        return table.update_item(
            Key={"pk": f"USER#{user_id}", "sk": sk},
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ReturnValues="ALL_NEW",
        )

    resp = _timed("update_item", sk, _run)
    return resp.get("Attributes", {})
