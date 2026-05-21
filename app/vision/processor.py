import base64
import json
import re
import time

import anthropic

from app.config import prompt_templates, settings
from app.models.chat import ImagePayload
from app.observability import get_logger
from app.vision.schemas import ImageAnalysisResult

log = get_logger("vision")

_VISION_PROMPT: str = prompt_templates["vision_prompt"].strip()

# Anthropic-supported image media types
_SUPPORTED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _extract_json(text: str) -> dict:
    """Extract JSON from model response, handling markdown code blocks."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()
    return json.loads(text)


def _detect_media_type(b64_data: str, declared: str) -> str:
    """Sniff actual image format from magic bytes; fall back to declared."""
    try:
        head = base64.b64decode(b64_data[:32], validate=False)[:16]
    except Exception:
        return declared if declared in _SUPPORTED_MEDIA_TYPES else "image/jpeg"

    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return declared if declared in _SUPPORTED_MEDIA_TYPES else "image/jpeg"


async def analyze_image(image: ImagePayload) -> ImageAnalysisResult:
    """Send image to vision model and return structured health analysis."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    media_type = _detect_media_type(image.data, image.mediaType)
    log.info("vision_call_start", extra={"model": settings.vision_model, "media_type": media_type})
    t0 = time.perf_counter()
    try:
        response = await client.messages.create(
            model=settings.vision_model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image.data,
                            },
                        },
                        {"type": "text", "text": _VISION_PROMPT},
                    ],
                }
            ],
        )
    except Exception as e:
        log.exception("vision_call_error", extra={"error_type": type(e).__name__})
        raise

    dt = round((time.perf_counter() - t0) * 1000, 1)
    raw = response.content[0].text
    try:
        parsed = _extract_json(raw)
    except Exception:
        log.exception("vision_parse_error", extra={"raw_preview": raw[:200]})
        raise

    image_type = parsed.get("image_type", "other")
    log.info("vision_call_ok", extra={"image_type": image_type, "duration_ms": dt})

    result = ImageAnalysisResult(
        image_type=image_type,
        structured_data=parsed.get("structured_data", {}),
        description=parsed.get("description", ""),
    )

    # Drop image bytes from local scope so they aren't retained anywhere.
    image.data = ""
    return result


def format_analysis_for_context(result: ImageAnalysisResult) -> str:
    """Format image analysis into a text block to bundle with the user message."""
    lines = [
        f"[Image Analysis — type: {result.image_type}]",
        f"Description: {result.description}",
        f"Extracted data: {json.dumps(result.structured_data, indent=2)}",
    ]
    return "\n".join(lines)
