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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kakao", tags=["kakao"])

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)


async def download_image(url: str, dest_path: Path) -> bool:
    """Download an image from a URL and save it to dest_path."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
            async with aiofiles.open(dest_path, "wb") as f:
                await f.write(response.content)
        return True
    except Exception as e:
        logger.error(f"Failed to download image from {url}: {e}")
        return False


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


@router.post("/webhook")
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

    # Try to extract image URL from payload
    image_url = extract_image_url(body)
    photo_path = None

    if image_url:
        # Generate unique filename
        ext = Path(image_url.split("?")[0]).suffix or ".jpg"
        filename = f"{uuid.uuid4()}{ext}"
        dest_path = UPLOAD_DIR / filename

        downloaded = await download_image(image_url, dest_path)
        if downloaded:
            photo_path = str(dest_path)
            logger.info(f"Image saved to {photo_path}")
        else:
            logger.warning(f"Could not download image from {image_url}")

    # Create submission record
    submission = Submission(
        parent_id=parent.id if parent else None,
        photo_path=photo_path,
        level=parent.level if parent else None,
        stage=None,
        extra_instruction=None,
        feedback_draft=None,
        status="pending",
    )

    # If no parent found, we still create a submission stub with kakao_user_id stored elsewhere
    # For now, store kakao_user_id temporarily in extra_instruction field if parent not found
    if not parent:
        submission.extra_instruction = f"[UNREGISTERED USER: {kakao_user_id}]"

    db.add(submission)
    db.commit()
    db.refresh(submission)

    logger.info(f"Created submission #{submission.id} for kakao_user_id={kakao_user_id}")

    if image_url:
        response_text = "사진을 받았어요! 선생님이 곧 피드백을 드릴게요 😊"
    else:
        # Text-only message - acknowledge but explain we need a photo
        utterance = body.get("userRequest", {}).get("utterance", "")
        logger.info(f"Text message received from {kakao_user_id}: {utterance}")
        response_text = "안녕하세요! 글쓰기 워크시트 사진을 보내주시면 선생님이 피드백을 드릴게요 📝"

    return build_kakao_response(response_text)
