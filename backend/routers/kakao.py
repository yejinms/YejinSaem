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


CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
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


def extract_image_url(body: dict) -> str | None:
    """
    Try to extract an image URL from various Kakao webhook payload formats.
    Kakao i Open Builder can send images in different ways depending on configuration.
    """
    # Check action detailParams for image
    detail_params = body.get("action", {}).get("detailParams", {})
    for key, val in detail_params.items():
        if isinstance(val, dict):
            origin = val.get("origin", "")
            if origin and (origin.startswith("http") and any(
                ext in origin.lower() for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]
            )):
                return origin

    # Check userRequest for attachment/image
    user_request = body.get("userRequest", {})
    utterance = user_request.get("utterance", "")

    # Some setups pass image URL as utterance
    if utterance.startswith("http") and any(
        ext in utterance.lower() for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]
    ):
        return utterance

    # Check for contexts or other nested locations
    contexts = body.get("contexts", [])
    for ctx in contexts:
        params = ctx.get("params", {})
        for key, val in params.items():
            if isinstance(val, dict):
                resolved = val.get("resolvedValue", "")
                if resolved and resolved.startswith("http"):
                    return resolved

    return None


@router.post("/webhook", dependencies=[Depends(verify_kakao_secret_header)])
async def kakao_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Receive webhook from Kakao i Open Builder.
    Handles incoming messages (especially image uploads) from parents.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    logger.info(f"Kakao webhook received: {body}")

    # Extract user ID
    kakao_user_id = (
        body.get("userRequest", {})
        .get("user", {})
        .get("id", "")
    )

    if not kakao_user_id:
        logger.warning("No kakao_user_id in webhook payload")
        return build_kakao_response("메시지를 처리할 수 없었어요. 다시 시도해 주세요.")

    # Find or note the parent (parent must be registered by admin first)
    parent = db.query(Parent).filter(Parent.kakao_user_id == kakao_user_id).first()
    if not parent:
        logger.info(f"Unregistered Kakao user attempted webhook: {kakao_user_id}")
        return build_kakao_response(
            "아직 등록된 학부모 정보가 없어요. 선생님께 카카오 사용자 ID를 알려주시면 등록 후 피드백을 받을 수 있어요."
        )

    # Try to extract image URL from payload
    image_url = extract_image_url(body)
    if not image_url:
        utterance = body.get("userRequest", {}).get("utterance", "")
        logger.info(f"Text message received from {kakao_user_id}: {utterance}")
        return build_kakao_response("안녕하세요! 글쓰기 워크시트 사진을 보내주시면 선생님이 피드백을 드릴게요 📝")

    downloaded = await download_image(image_url)
    if not downloaded:
        logger.warning(f"Could not download image from {image_url}")
        return build_kakao_response("사진을 불러오지 못했어요. 다시 보내주세요.")

    image_content, content_type = downloaded
    try:
        validate_image_content(image_content, content_type)
    except HTTPException as e:
        logger.warning(f"Rejected Kakao image from {kakao_user_id}: {e.detail}")
        return build_kakao_response("지원하지 않는 이미지 형식이에요. JPG, PNG, GIF, WebP 사진으로 다시 보내주세요.")

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
    return build_kakao_response("사진을 받았어요! 선생님이 곧 피드백을 드릴게요 😊")
