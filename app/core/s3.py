import os
from collections.abc import Iterator

import boto3

from app.config import settings
from app.observability import get_logger

log = get_logger("core.s3")

if not os.environ.get("AWS_EXECUTION_ENV") and not os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"):
    os.environ.setdefault("AWS_PROFILE", settings.aws_profile)

_s3_client = None

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def get_s3_client():
    global _s3_client
    if _s3_client is None:
        # Explicit regional endpoint so presigned URLs sign against
        # s3.<region>.amazonaws.com — the default global endpoint would
        # 307-redirect and break SigV4 (host changes after redirect).
        _s3_client = boto3.client(
            "s3",
            region_name=settings.aws_region,
            endpoint_url=f"https://s3.{settings.aws_region}.amazonaws.com",
        )
    return _s3_client


def _batched(values: list[str], size: int) -> Iterator[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _extension_for(media_type: str) -> str:
    return _EXTENSIONS.get(media_type, ".bin")


def upload_image_bytes(
    user_id: str,
    session_id: str,
    msg_id: str,
    media_type: str,
    raw_bytes: bytes,
) -> str:
    s3_key = f"chats/{user_id}/{session_id}/{msg_id}{_extension_for(media_type)}"
    try:
        get_s3_client().put_object(
            Bucket=settings.chat_media_bucket,
            Key=s3_key,
            Body=raw_bytes,
            ContentType=media_type,
        )
    except Exception as exc:
        log.exception(
            "image_upload_error",
            extra={"session_id": session_id, "message_id": msg_id, "error_type": type(exc).__name__},
        )
        raise

    log.info("image_upload_ok", extra={"session_id": session_id, "message_id": msg_id, "s3_key": s3_key})
    return s3_key


def presign_get(s3_key: str) -> str:
    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.chat_media_bucket, "Key": s3_key},
        ExpiresIn=settings.presigned_url_ttl_seconds,
    )


def delete_objects_by_prefix(prefix: str) -> int:
    deleted = 0
    paginator = get_s3_client().get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=settings.chat_media_bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            keys.append(item["Key"])

    for chunk in _batched(keys, 1000):
        get_s3_client().delete_objects(
            Bucket=settings.chat_media_bucket,
            Delete={"Objects": [{"Key": key} for key in chunk]},
        )
        deleted += len(chunk)

    return deleted