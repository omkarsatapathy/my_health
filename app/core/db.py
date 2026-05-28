import os
import time

import boto3
from boto3.dynamodb.conditions import Key

from app.config import settings
from app.observability import get_logger
from app.status_events import db as status_db

_DB_LABELS = {
    "query_sk_prefix": "Reading DB",
    "get_item": "Reading DB",
    "put_item": "Writing DB",
    "update_item": "Updating DB",
}

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
    status_db(_DB_LABELS.get(op, "DB access"))
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
