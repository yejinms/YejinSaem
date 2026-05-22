"""
validation.py - Shared validation and security helpers for YejinSaem.
"""

import hmac
import os
from pathlib import Path
from urllib.parse import unquote

from fastapi import Header, HTTPException, UploadFile, status

VALID_LEVELS = ["표현력", "초등기초", "초등심화"]
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def configured_env(name: str) -> str | None:
    """Return an env var only when it looks intentionally configured."""
    value = os.getenv(name, "").strip()
    if not value or value.startswith("your_"):
        return None
    return value


def normalize_phone_number(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.replace("-", "").replace(" ", "").strip()
    if normalized and not normalized.isdigit():
        raise HTTPException(status_code=400, detail="전화번호는 숫자만 입력해주세요.")
    return normalized or None


def validate_level(level: str) -> None:
    if level not in VALID_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid level. Must be one of: {VALID_LEVELS}",
        )


def validate_child_age(age: int | None) -> None:
    if age is not None and not (5 <= age <= 15):
        raise HTTPException(status_code=400, detail="아이 나이는 5세에서 15세 사이로 입력해주세요.")


def validate_image_filename(filename: str | None) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="지원하지 않는 이미지 형식입니다.")
    return ext


def validate_image_content(content: bytes, content_type: str | None = None) -> None:
    if not content:
        raise HTTPException(status_code=400, detail="이미지 파일이 비어 있습니다.")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="이미지 파일은 10MB 이하로 업로드해주세요.")
    if content_type and content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="지원하지 않는 이미지 형식입니다.")


async def read_validated_upload(photo: UploadFile) -> tuple[bytes, str]:
    ext = validate_image_filename(photo.filename)
    content = await photo.read()
    validate_image_content(content, photo.content_type)
    return content, ext


def verify_admin(authorization: str | None = Header(default=None)) -> None:
    password = configured_env("ADMIN_PASSWORD")
    if not password:
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="관리자 인증이 필요합니다.",
        )

    provided = authorization.removeprefix("Bearer ").strip()
    decoded = unquote(provided)
    if not hmac.compare_digest(decoded.encode("utf-8"), password.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="관리자 인증이 필요합니다.",
        )


def verify_kakao_secret_header(
    x_kakao_secret: str | None = Header(default=None),
    x_kakao_channel_secret: str | None = Header(default=None),
) -> None:
    secret = configured_env("KAKAO_CHANNEL_SECRET")
    if not secret:
        return

    provided = x_kakao_secret or x_kakao_channel_secret
    # Open Builder does not send custom headers; only reject when a wrong secret is sent.
    if not provided:
        return
    if not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=401, detail="Invalid Kakao webhook secret")
