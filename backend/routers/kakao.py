"""
kakao.py - Kakao i Open Builder webhook receiver
"""

import logging
import os
import uuid
from pathlib import Path

import aiofiles
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import Submission, Parent, get_db
from services.kakao_service import build_kakao_response
from validation import (
    ALLOWED_IMAGE_EXTENSIONS,
    validate_image_content,
    verify_kakao_secret_header,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kakao", tags=["kakao"])

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)


def _skill_json(text: str, status_code: int = 200) -> JSONResponse:
    """Always return Open Builder skill response shape (never FastAPI error JSON)."""
    return JSONResponse(
        status_code=status_code,
        content=build_kakao_response(text),
        media_type="application/json; charset=utf-8",
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


def extract_image_url(body: dict) -> str | None:
    """
    Try to extract an image URL from various Kakao webhook payload formats.
    Kakao Open Builder and related message flows can place image URLs in
    attachment payloads, action detailParams, or nested params objects.
    """
    # Check the payload recursively, prioritizing explicit image-related keys.
    prioritized_roots = [
        body.get("userRequest", {}),
        body.get("action", {}),
        body.get("contexts", []),
    ]
    for root in prioritized_roots:
        found = _extract_image_url_from_obj(root)
        if found:
            return found

    return _extract_image_url_from_obj(body)


@router.post("/webhook", dependencies=[Depends(verify_kakao_secret_header)])
async def kakao_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Receive webhook from Kakao i Open Builder.
    Handles incoming messages (especially image uploads) from parents.
    """
    try:
        body = await request.json()
    except Exception:
        logger.warning("Kakao webhook received non-JSON body")
        return _skill_json("요청 형식을 읽을 수 없어요. 오픈빌더 스킬 테스트 JSON을 확인해 주세요.")

    try:
        return await _handle_kakao_webhook(body, db)
    except Exception:
        logger.exception("Kakao webhook handler failed")
        return _skill_json("잠시 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")


async def _handle_kakao_webhook(body: dict, db: Session) -> JSONResponse:
    logger.info(f"Kakao webhook received: {body}")

    kakao_user_id = (
        body.get("userRequest", {})
        .get("user", {})
        .get("id", "")
    )

    if not kakao_user_id:
        logger.warning("No kakao_user_id in webhook payload")
        return _skill_json("메시지를 처리할 수 없었어요. 다시 시도해 주세요.")

    parent = db.query(Parent).filter(Parent.kakao_user_id == kakao_user_id).first()
    if not parent:
        logger.info(f"Unregistered Kakao user attempted webhook: {kakao_user_id}")
        return _skill_json(
            "아직 등록된 학부모 정보가 없어요. 선생님께 카카오 사용자 ID를 알려주시면 등록 후 피드백을 받을 수 있어요."
        )

    image_url = extract_image_url(body)
    if not image_url:
        utterance = body.get("userRequest", {}).get("utterance", "")
        logger.info(f"Text message received from {kakao_user_id}: {utterance}")
        return _skill_json(
            "안녕하세요! 글쓰기 워크시트 사진을 보내주시면 선생님이 피드백을 드릴게요."
        )

    downloaded = await download_image(image_url)
    if not downloaded:
        logger.warning(f"Could not download image from {image_url}")
        return _skill_json("사진을 불러오지 못했어요. 다시 보내주세요.")

    image_content, content_type = downloaded
    try:
        validate_image_content(image_content, content_type)
    except HTTPException as e:
        logger.warning(f"Rejected Kakao image from {kakao_user_id}: {e.detail}")
        return _skill_json(
            "지원하지 않는 이미지 형식이에요. JPG, PNG, GIF, WebP 사진으로 다시 보내주세요."
        )

    ext = image_extension_from_url_or_type(image_url, content_type)
    filename = f"{uuid.uuid4()}{ext}"
    dest_path = UPLOAD_DIR / filename
    async with aiofiles.open(dest_path, "wb") as f:
        await f.write(image_content)

    photo_path = str(dest_path)
    logger.info(f"Image saved to {photo_path}")

    submission = Submission(
        parent_id=parent.id,
        photo_path=photo_path,
        level=parent.level,
        stage=None,
        extra_instruction=None,
        feedback_draft=None,
        status="pending",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    logger.info(f"Created submission #{submission.id} for kakao_user_id={kakao_user_id}")
    return _skill_json("사진을 받았어요! 선생님이 곧 피드백을 드릴게요.")
