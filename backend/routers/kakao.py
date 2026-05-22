"""
kakao.py - Kakao i Open Builder webhook + Make.com 연동
"""

import logging
import os
import uuid
from pathlib import Path

import aiofiles
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from database import Parent, Submission, get_db
from services.kakao_service import build_kakao_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kakao", tags=["kakao"])

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)


class MakeIncoming(BaseModel):
    """Make.com HTTP 모듈에서 보내기 쉬운 단순 형식."""

    kakao_user_id: str
    image_url: HttpUrl
    message: str | None = None


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


async def create_submission_from_image(
    db: Session,
    parent: Parent,
    image_url: str,
    extra_note: str | None = None,
) -> Submission:
    """학부모·이미지 URL로 pending 제출 생성."""
    ext = Path(image_url.split("?")[0]).suffix or ".jpg"
    filename = f"{uuid.uuid4()}{ext}"
    dest_path = UPLOAD_DIR / filename

    downloaded = await download_image(image_url, str(dest_path))
    photo_path = str(dest_path) if downloaded else None
    if not photo_path:
        raise HTTPException(
            status_code=400,
            detail="이미지를 다운로드하지 못했습니다. URL이 공개 접근 가능한지 확인해 주세요.",
        )

    submission = Submission(
        parent_id=parent.id,
        photo_path=photo_path,
        level=parent.level,
        stage=None,
        extra_instruction=extra_note,
        feedback_draft=None,
        status="pending",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    logger.info(f"Created submission #{submission.id} for parent_id={parent.id}")
    return submission


def _check_make_secret(x_make_secret: str | None) -> None:
    expected = os.getenv("MAKE_WEBHOOK_SECRET", "").strip()
    if not expected:
        return
    if x_make_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


def extract_image_url(body: dict) -> str | None:
    """
    Try to extract an image URL from various Kakao webhook payload formats.
    Kakao i Open Builder can send images in different ways depending on configuration.
    """
    detail_params = body.get("action", {}).get("detailParams", {})
    for key, val in detail_params.items():
        if isinstance(val, dict):
            origin = val.get("origin", "")
            if origin and (
                origin.startswith("http")
                and any(
                    ext in origin.lower()
                    for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]
                )
            ):
                return origin

    user_request = body.get("userRequest", {})
    utterance = user_request.get("utterance", "")

    if utterance.startswith("http") and any(
        ext in utterance.lower() for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]
    ):
        return utterance

    contexts = body.get("contexts", [])
    for ctx in contexts:
        params = ctx.get("params", {})
        for key, val in params.items():
            if isinstance(val, dict):
                resolved = val.get("resolvedValue", "")
                if resolved and resolved.startswith("http"):
                    return resolved

    return None


@router.post("/make")
async def make_incoming(
    body: MakeIncoming,
    db: Session = Depends(get_db),
    x_make_secret: str | None = Header(default=None, alias="X-Make-Secret"),
):
    """
    Make.com 시나리오 → 예진샘 서버.

    Make HTTP 모듈 설정 예:
    - URL: https://<공개도메인>/kakao/make
    - Method: POST
    - Body type: JSON
    - Headers (선택): X-Make-Secret: <MAKE_WEBHOOK_SECRET>
    """
    _check_make_secret(x_make_secret)

    parent = (
        db.query(Parent).filter(Parent.kakao_user_id == body.kakao_user_id).first()
    )
    if not parent:
        raise HTTPException(
            status_code=404,
            detail=(
                f"등록되지 않은 카카오 사용자입니다 (id={body.kakao_user_id}). "
                "관리자 대시보드에서 학부모를 먼저 등록해 주세요."
            ),
        )

    submission = await create_submission_from_image(
        db,
        parent,
        str(body.image_url),
        extra_note=body.message,
    )

    return {
        "ok": True,
        "submission_id": submission.id,
        "status": submission.status,
        "child_name": parent.child_name,
        "message": "대기 목록에 추가되었습니다.",
    }


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

    kakao_user_id = body.get("userRequest", {}).get("user", {}).get("id", "")

    if not kakao_user_id:
        logger.warning("No kakao_user_id in webhook payload")
        return build_kakao_response("메시지를 처리할 수 없었어요. 다시 시도해 주세요.")

    parent = db.query(Parent).filter(Parent.kakao_user_id == kakao_user_id).first()
    if not parent:
        logger.warning(f"Unregistered kakao_user_id: {kakao_user_id}")
        return build_kakao_response(
            "아직 등록되지 않은 채널이에요. 선생님께 문의해 주세요."
        )

    image_url = extract_image_url(body)

    if image_url:
        try:
            submission = await create_submission_from_image(db, parent, image_url)
            logger.info(f"Open Builder submission #{submission.id}")
        except HTTPException:
            return build_kakao_response(
                "사진을 받지 못했어요. 다시 보내주시거나 선생님께 알려 주세요."
            )
        return build_kakao_response("사진을 받았어요! 선생님이 곧 피드백을 드릴게요 😊")

    utterance = body.get("userRequest", {}).get("utterance", "")
    logger.info(f"Text message from {kakao_user_id}: {utterance}")
    return build_kakao_response(
        "안녕하세요! 글쓰기 워크시트 사진을 보내주시면 선생님이 피드백을 드릴게요 📝"
    )
