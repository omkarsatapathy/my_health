import os

import boto3
from boto3.dynamodb.conditions import Key

from app.config import settings

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


def query_sk_prefix(user_id: str, sk_prefix: str) -> list[dict]:
    """Query all items for a user where SK begins with sk_prefix."""
    table = get_table()
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{user_id}") & Key("sk").begins_with(sk_prefix)
    )
    return resp.get("Items", [])


def put_item(user_id: str, sk: str, data: dict) -> None:
    """Write a single item; pk and sk are injected automatically."""
    table = get_table()
    table.put_item(Item={"pk": f"USER#{user_id}", "sk": sk, **data})


def get_item(user_id: str, sk: str) -> dict | None:
    """Fetch a single item by exact pk + sk."""
    table = get_table()
    resp = table.get_item(Key={"pk": f"USER#{user_id}", "sk": sk})
    return resp.get("Item")


def update_item(user_id: str, sk: str, fields: dict) -> dict:
    """Partially update an item's fields."""
    table = get_table()
    expr = "SET " + ", ".join(f"#f{i} = :v{i}" for i in range(len(fields)))
    names = {f"#f{i}": k for i, k in enumerate(fields)}
    values = {f":v{i}": v for i, v in enumerate(fields.values())}
    resp = table.update_item(
        Key={"pk": f"USER#{user_id}", "sk": sk},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )
    return resp.get("Attributes", {})
