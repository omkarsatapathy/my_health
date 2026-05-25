import base64
import json
from datetime import UTC, datetime
from decimal import Decimal

import anthropic
from boto3.dynamodb.conditions import Key
from ulid import ULID

from app.config import DEFAULT_USER_ID, prompt_templates, settings
from app.core.db import get_item, get_table, put_item
from app.core.s3 import delete_objects_by_prefix, presign_get
from app.models.chat import ChatMessage, ImagePayload, SessionDetail, SessionSummary
from app.observability import get_logger

log = get_logger("core.chat_store")

SESSION_PREFIX = "CHATHDR#"
MESSAGE_PREFIX = "CHATMSG#"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _pk(user_id: str) -> str:
    return f"USER#{user_id or DEFAULT_USER_ID}"


def _session_sk(session_id: str) -> str:
    return f"{SESSION_PREFIX}{session_id}"


def _message_sk(session_id: str, msg_id: str) -> str:
    return f"{MESSAGE_PREFIX}{session_id}#{msg_id}"


def _coerce_number(value):
    if isinstance(value, Decimal):
        return int(value)
    return value


def _encode_cursor(last_evaluated_key: dict | None) -> str | None:
    if not last_evaluated_key:
        return None
    payload = json.dumps(last_evaluated_key).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("utf-8")


def _decode_cursor(cursor: str | None) -> dict | None:
    if not cursor:
        return None
    return json.loads(base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8"))


def _session_summary_from_item(item: dict) -> SessionSummary:
    return SessionSummary(
        session_id=item["session_id"],
        title=item.get("title", "New chat"),
        created_at=item["created_at"],
        updated_at=item["updated_at"],
        message_count=_coerce_number(item.get("message_count", 0)),
        last_preview=item.get("last_preview", ""),
    )


def _image_payload_from_item(image: dict | None) -> ImagePayload | None:
    if not image:
        return None
    payload = ImagePayload(
        mediaType=image.get("media_type", "image/jpeg"),
        encoding="base64",
        data=None,
        url=presign_get(image["s3_key"]) if image.get("s3_key") else None,
        s3_key=image.get("s3_key"),
        vision_summary=image.get("vision_summary"),
        width=_coerce_number(image.get("width")),
        height=_coerce_number(image.get("height")),
    )
    return payload


def _chat_message_from_item(item: dict) -> ChatMessage:
    return ChatMessage(
        role=item["role"],
        content=item.get("content", ""),
        image=_image_payload_from_item(item.get("image")),
        session_id=item.get("session_id"),
        message_id=item.get("message_id"),
        created_at=item.get("created_at"),
        incomplete=bool(item.get("incomplete", False)),
    )


def _preview_from_content(content: str) -> str:
    return (content or "").strip().replace("\n", " ")[:120]


def new_session_id() -> str:
    return str(ULID())


def new_message_id() -> str:
    return str(ULID())


def create_session(user_id: str, title: str = "New chat") -> SessionSummary:
    session_id = new_session_id()
    now = _now_iso()
    item = {
        "session_id": session_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
        "last_preview": "",
        "archived": False,
    }
    put_item(user_id, _session_sk(session_id), item)
    summary = _session_summary_from_item(item)
    log.info("session_create", extra={"session_id": session_id})
    return summary


def get_session(user_id: str, session_id: str) -> SessionSummary | None:
    item = get_item(user_id, _session_sk(session_id))
    if not item:
        return None
    return _session_summary_from_item(item)


def list_sessions(user_id: str, limit: int | None = None, cursor: str | None = None) -> tuple[list[SessionSummary], str | None]:
    table = get_table()
    query_kwargs = {
        "KeyConditionExpression": Key("pk").eq(_pk(user_id)) & Key("sk").begins_with(SESSION_PREFIX),
        "ScanIndexForward": False,
        "Limit": limit or settings.session_list_page_size,
    }
    decoded_cursor = _decode_cursor(cursor)
    if decoded_cursor:
        query_kwargs["ExclusiveStartKey"] = decoded_cursor
    response = table.query(
        **query_kwargs,
    )
    sessions = [_session_summary_from_item(item) for item in response.get("Items", [])]
    next_cursor = _encode_cursor(response.get("LastEvaluatedKey"))
    log.info(
        "session_list",
        extra={"count": len(sessions), "has_cursor": bool(next_cursor)},
    )
    return sessions, next_cursor


def get_session_messages(user_id: str, session_id: str) -> list[ChatMessage]:
    table = get_table()
    items: list[dict] = []
    last_evaluated_key = None
    while True:
        query_kwargs = {
            "KeyConditionExpression": Key("pk").eq(_pk(user_id)) & Key("sk").begins_with(f"{MESSAGE_PREFIX}{session_id}#"),
            "ScanIndexForward": True,
        }
        if last_evaluated_key:
            query_kwargs["ExclusiveStartKey"] = last_evaluated_key
        response = table.query(**query_kwargs)
        items.extend(response.get("Items", []))
        last_evaluated_key = response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break
    messages = [_chat_message_from_item(item) for item in items]
    image_count = sum(1 for item in items if item.get("image", {}).get("s3_key"))
    log.info(
        "session_messages_load",
        extra={"session_id": session_id, "message_count": len(messages), "image_count": image_count},
    )
    return messages


def append_message(
    user_id: str,
    session_id: str,
    role: str,
    content: str,
    image: dict | None = None,
    incomplete: bool = False,
    message_id: str | None = None,
) -> ChatMessage:
    table = get_table()
    msg_id = message_id or new_message_id()
    now = _now_iso()
    item = {
        "session_id": session_id,
        "message_id": msg_id,
        "role": role,
        "content": content,
        "created_at": now,
        "incomplete": incomplete,
    }
    if image:
        item["image"] = image
    table.put_item(Item={"pk": _pk(user_id), "sk": _message_sk(session_id, msg_id), **item})
    if role == "user":
        table.update_item(
            Key={"pk": _pk(user_id), "sk": _session_sk(session_id)},
            UpdateExpression=(
                "SET updated_at = :updated_at, last_preview = :last_preview "
                "ADD message_count :message_increment"
            ),
            ExpressionAttributeValues={
                ":updated_at": now,
                ":last_preview": _preview_from_content(content),
                ":message_increment": 1,
            },
        )
    else:
        table.update_item(
            Key={"pk": _pk(user_id), "sk": _session_sk(session_id)},
            UpdateExpression="SET updated_at = :updated_at ADD message_count :message_increment",
            ExpressionAttributeValues={
                ":updated_at": now,
                ":message_increment": 1,
            },
        )
    return _chat_message_from_item(item)


def rename_session(user_id: str, session_id: str, new_title: str) -> SessionSummary | None:
    table = get_table()
    now = _now_iso()
    response = table.update_item(
        Key={"pk": _pk(user_id), "sk": _session_sk(session_id)},
        UpdateExpression="SET title = :title, updated_at = :updated_at",
        ExpressionAttributeValues={":title": new_title, ":updated_at": now},
        ReturnValues="ALL_NEW",
    )
    attributes = response.get("Attributes")
    if not attributes:
        return None
    return _session_summary_from_item(attributes)


def delete_session(user_id: str, session_id: str) -> tuple[int, int]:
    table = get_table()
    items: list[dict] = []
    last_evaluated_key = None
    while True:
        query_kwargs = {
            "KeyConditionExpression": Key("pk").eq(_pk(user_id)) & Key("sk").begins_with(f"{MESSAGE_PREFIX}{session_id}#"),
            "ProjectionExpression": "pk, sk",
        }
        if last_evaluated_key:
            query_kwargs["ExclusiveStartKey"] = last_evaluated_key
        response = table.query(**query_kwargs)
        items.extend(response.get("Items", []))
        last_evaluated_key = response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break
    deleted_s3 = delete_objects_by_prefix(f"chats/{user_id}/{session_id}/")
    with table.batch_writer() as batch:
        batch.delete_item(Key={"pk": _pk(user_id), "sk": _session_sk(session_id)})
        for item in items:
            batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
    log.info(
        "session_delete",
        extra={"session_id": session_id, "deleted_message_count": len(items), "deleted_s3_object_count": deleted_s3},
    )
    return len(items), deleted_s3


def mark_assistant_incomplete(user_id: str, session_id: str, msg_id: str) -> None:
    table = get_table()
    table.update_item(
        Key={"pk": _pk(user_id), "sk": _message_sk(session_id, msg_id)},
        UpdateExpression="SET incomplete = :incomplete",
        ExpressionAttributeValues={":incomplete": True},
    )
    log.info("assistant_message_incomplete", extra={"session_id": session_id, "message_id": msg_id})


async def update_session_title_from_first_turn(
    user_id: str,
    session_id: str,
    first_user_text: str,
    first_assistant_text: str,
) -> None:
    prompt = prompt_templates["session_title"].format(
        first_user_text=first_user_text.strip(),
        first_assistant_text=first_assistant_text.strip(),
    )
    title = " ".join(first_user_text.strip().split()[:6]).strip() or "New chat"
    try:
        response = await anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key).messages.create(
            model=settings.chat_model,
            max_tokens=24,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        candidate = response.content[0].text.strip().replace('"', "")
        if candidate:
            title = candidate[:80]
    except Exception as exc:
        log.exception("title_generate_error", extra={"session_id": session_id, "error_type": type(exc).__name__})

    summary = rename_session(user_id, session_id, title)
    if summary:
        log.info("title_generated", extra={"session_id": session_id, "title": summary.title})


def get_session_detail(user_id: str, session_id: str) -> SessionDetail | None:
    session = get_session(user_id, session_id)
    if not session:
        return None
    return SessionDetail(session_id=session.session_id, title=session.title, messages=get_session_messages(user_id, session_id))