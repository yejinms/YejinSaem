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
from services.kakao_service import build_kakao_response
from services.parent_match import extract_phone_from_text, resolve_parent
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


def _extract_openbuilder_image_url(body: dict) -> str | None:
    action = body.get("action") or {}
    detail_params = action.get("detailParams") or {}
    secure = detail_params.get("secureimage") or {}
    if isinstance(secure, dict):
        for key in ("origin", "value"):
            for url in _urls_from_secureimage_value(str(secure.get(key) or "")):
                return url

    params = action.get("params") or {}
    for url in _urls_from_secureimage_value(str(params.get("secureimage") or "")):
        return url

    user_params = (body.get("userRequest") or {}).get("params") or {}
    media = user_params.get("media") or {}
    if isinstance(media, dict):
        media_url = media.get("url")
        if isinstance(media_url, str) and media_url.startswith("http"):
            return media_url

    return None


SUBMISSION_INTENT_KEYWORDS = ("첨삭", "피드백", "사진", "워크시트", "글쓰기", "이미지")


def wants_submission_help(utterance: str) -> bool:
    normalized = (utterance or "").replace(" ", "")
    return any(keyword in normalized for keyword in SUBMISSION_INTENT_KEYWORDS)


def extract_image_url(body: dict) -> str | None:
    """
    Try to extract an image URL from various Kakao webhook payload formats.
    Kakao Open Builder and related message flows can place image URLs in
    attachment payloads, action detailParams, or nested params objects.
    """
    found = _extract_openbuilder_image_url(body)
    if found:
        return found

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
    parent, link_message, phone_just_linked = resolve_parent(db, kakao_user_id, utterance)
    if link_message:
        logger.info(
            "Kakao user link issue: bot_user_key=%s utterance=%r",
            kakao_user_id,
            utterance[:80],
        )
        return _skill_json(link_message)
    if not parent:
        return _skill_json("등록 정보를 찾을 수 없어요. 선생님께 문의해 주세요.")

    image_url = extract_image_url(body)
    if not image_url:
        logger.info(f"Text message received from {kakao_user_id}: {utterance}")
        if phone_just_linked:
            return _skill_json(
                "등록 확인되었어요! 글쓰기 워크시트 사진을 보내주시면 선생님이 피드백을 드릴게요."
            )
        if wants_submission_help(utterance):
            return _skill_json(
                "채팅창에 글만내면 사진이 전달되지 않을 수 있어요. "
                "시나리오의 「사진 보내기」 또는 「이미지 보안전송」 버튼으로 워크시트 사진을 보내주세요."
            )
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
