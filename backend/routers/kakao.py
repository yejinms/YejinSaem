"""
kakao.py - Kakao i Open Builder webhook receiver
"""

import json
import logging
import os
import re
import uuid
from pathlib import Path

import aiofiles
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import Submission, get_db
from routers.admin import serialize_photo_paths
from services.kakao_service import build_kakao_response
from services.parent_match import CHANNEL_GREETING, resolve_parent
from validation import (
    ALLOWED_IMAGE_EXTENSIONS,
    validate_image_content,
    verify_kakao_secret_header,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kakao", tags=["kakao"])

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)


def _skill_json(text: str, status_code: int = 200) -> Response:
    """Always return Open Builder skill response shape (never FastAPI error JSON)."""
    body = json.dumps(
        build_kakao_response(text),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return Response(
        content=body,
        status_code=status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

IMAGE_URL_KEYS = {
    "url",
    "imageUrl",
    "imageURL",
    "image_url",
    "origin",
    "resolvedValue",
    "downloadUrl",
    "fileUrl",
    "resourceUrl",
}

IMAGE_HINT_KEYS = {
    "attachment",
    "detailParams",
    "params",
    "payload",
    "content",
    "image",
    "data",
}


async def download_image(url: str) -> tuple[bytes, str | None] | None:
    """Download an image from a URL and return bytes plus content type."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content, response.headers.get("content-type", "").split(";")[0]
    except Exception as e:
        logger.error(f"Failed to download image from {url}: {e}")
        return None


def image_extension_from_url_or_type(url: str, content_type: str | None) -> str:
    ext = Path(url.split("?")[0]).suffix.lower()
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        return ext
    return CONTENT_TYPE_EXTENSIONS.get(content_type or "", ".jpg")


def _looks_like_image_url(value: str) -> bool:
    if not value.startswith("http"):
        return False

    lowered = value.lower()
    return any(ext in lowered for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"])


def _extract_image_url_from_obj(obj, parent_key: str | None = None) -> str | None:
    if isinstance(obj, dict):
        # Prefer explicit image URL keys first.
        for key in IMAGE_URL_KEYS:
            value = obj.get(key)
            if isinstance(value, str) and value.startswith("http"):
                if _looks_like_image_url(value) or key in {"imageUrl", "imageURL", "image_url", "origin", "resolvedValue", "downloadUrl", "fileUrl", "resourceUrl"}:
                    return value

        for key, value in obj.items():
            if isinstance(value, str) and value.startswith("http"):
                if key in IMAGE_URL_KEYS and (parent_key in IMAGE_HINT_KEYS or _looks_like_image_url(value)):
                    return value

            found = _extract_image_url_from_obj(value, key)
            if found:
                return found

    if isinstance(obj, list):
        for item in obj:
            found = _extract_image_url_from_obj(item, parent_key)
            if found:
                return found

    if isinstance(obj, str) and _looks_like_image_url(obj):
        return obj

    return None


def _urls_from_secureimage_value(value: str) -> list[str]:
    """Parse Open Builder @sys.plugin.secureimage origin/value payloads."""
    if not value:
        return []

    text = value.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            text = str(parsed.get("secureUrls") or text)
    except json.JSONDecodeError:
        pass

    return re.findall(r"https?://[^\s\),\"']+", text)


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def _extract_openbuilder_image_urls(body: dict) -> list[str]:
    urls: list[str] = []
    action = body.get("action") or {}
    detail_params = action.get("detailParams") or {}
    secure = detail_params.get("secureimage") or {}
    if isinstance(secure, dict):
        for key in ("origin", "value"):
            urls.extend(_urls_from_secureimage_value(str(secure.get(key) or "")))

    params = action.get("params") or {}
    urls.extend(_urls_from_secureimage_value(str(params.get("secureimage") or "")))

    user_params = (body.get("userRequest") or {}).get("params") or {}
    media = user_params.get("media") or {}
    if isinstance(media, dict):
        media_url = media.get("url")
        if isinstance(media_url, str) and media_url.startswith("http"):
            urls.append(media_url)

    return _dedupe_urls(urls)


def extract_image_urls(body: dict) -> list[str]:
    """
    Collect image URLs from Kakao Open Builder payloads (supports multi-image secureimage).
    """
    urls = _extract_openbuilder_image_urls(body)
    if urls:
        return urls

    for root in (
        body.get("userRequest", {}),
        body.get("action", {}),
        body.get("contexts", []),
        body,
    ):
        found = _extract_image_url_from_obj(root)
        if found:
            return [found]

    return []


def extract_image_url(body: dict) -> str | None:
    """First image URL, if any (backward compatible)."""
    urls = extract_image_urls(body)
    return urls[0] if urls else None


async def save_uploaded_image(url: str) -> str | None:
    downloaded = await download_image(url)
    if not downloaded:
        return None

    image_content, content_type = downloaded
    validate_image_content(image_content, content_type)

    ext = image_extension_from_url_or_type(url, content_type)
    filename = f"{uuid.uuid4()}{ext}"
    dest_path = UPLOAD_DIR / filename
    async with aiofiles.open(dest_path, "wb") as f:
        await f.write(image_content)
    return str(dest_path)


@router.api_route(
    "/webhook",
    methods=["GET", "HEAD", "POST"],
    dependencies=[Depends(verify_kakao_secret_header)],
)
async def kakao_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Receive webhook from Kakao i Open Builder.
    Handles incoming messages (especially image uploads) from parents.
    """
    if request.method == "HEAD":
        return Response(status_code=200)
    if request.method == "GET":
        # Open Builder may probe the URL with GET before POST skill tests.
        return _skill_json("스킬 서버 연결이 확인되었습니다.")

    raw = await request.body()
    logger.info(
        "Kakao webhook POST headers=%s body_len=%s body_preview=%s",
        dict(request.headers),
        len(raw),
        raw[:500],
    )

    try:
        if not raw:
            body = None
        else:
            body = json.loads(raw.decode("utf-8"))
    except Exception:
        logger.warning("Kakao webhook received non-JSON body")
        return _skill_json("요청 형식을 읽을 수 없어요. 오픈빌더 스킬 테스트 JSON을 확인해 주세요.")

    try:
        return await _handle_kakao_webhook(body, db)
    except Exception:
        logger.exception("Kakao webhook handler failed")
        return _skill_json("잠시 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")


async def _handle_kakao_webhook(body: dict, db: Session) -> Response:
    logger.info(f"Kakao webhook received: {body}")

    if not isinstance(body, dict):
        logger.warning("Kakao webhook body is not a JSON object: %r", body)
        return _skill_json("요청 형식을 읽을 수 없어요. 스킬 테스트 JSON을 확인해 주세요.")

    kakao_user_id = (
        body.get("userRequest", {})
        .get("user", {})
        .get("id", "")
    )

    if not kakao_user_id:
        logger.warning("No kakao_user_id in webhook payload")
        return _skill_json("메시지를 처리할 수 없었어요. 다시 시도해 주세요.")

    utterance = body.get("userRequest", {}).get("utterance", "") or ""
    image_urls = extract_image_urls(body)
    parent = resolve_parent(db, kakao_user_id)

    if not parent:
        if image_urls:
            logger.warning(
                "Kakao image from unlinked user (set botUserKey in admin): bot_user_key=%s",
                kakao_user_id,
            )
        else:
            logger.info(
                "Kakao text from unlinked user: bot_user_key=%s utterance=%r",
                kakao_user_id,
                utterance[:80],
            )
        return _skill_json(CHANNEL_GREETING)

    if not image_urls:
        logger.info(f"Text message received from {kakao_user_id}: {utterance}")
        return _skill_json(CHANNEL_GREETING)

    saved_paths: list[str] = []
    for image_url in image_urls:
        try:
            path = await save_uploaded_image(image_url)
            if path:
                saved_paths.append(path)
                logger.info("Image saved to %s", path)
        except HTTPException as e:
            logger.warning(
                "Rejected Kakao image from %s (%s): %s",
                kakao_user_id,
                image_url,
                e.detail,
            )
        except Exception:
            logger.exception("Failed to save Kakao image from %s", image_url)

    if not saved_paths:
        return _skill_json("사진을 불러오지 못했어요. 다시 보내주세요.")

    submission = Submission(
        parent_id=parent.id,
        photo_path=serialize_photo_paths(saved_paths),
        level=parent.level,
        stage=None,
        extra_instruction=None,
        feedback_draft=None,
        status="pending",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    logger.info(
        "Created submission #%s for kakao_user_id=%s with %s image(s)",
        submission.id,
        kakao_user_id,
        len(saved_paths),
    )
    if len(saved_paths) == 1:
        reply = "사진을 받았어요! 선생님 확인 후 평균 3시간 이내에 상세한 피드백을 전달드릴게요. 감사합니다 :)"
    else:
        reply = (
            f"사진 {len(saved_paths)}장을 받았어요! "
            "선생님 확인 후 평균 3시간 이내에 상세한 피드백을 전달드릴게요. 감사합니다 :)"
        )
    return _skill_json(reply)
