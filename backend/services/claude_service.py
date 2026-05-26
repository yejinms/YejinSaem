"""
claude_service.py - Claude AI integration for generating writing feedback
"""

import base64
import io
import logging
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from PIL import Image

from prompts import get_feedback_user_prompt, get_system_prompt
from upload_paths import resolve_upload_file_path

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

# Anthropic vision limit: 5_242_880 bytes per image
MAX_ANTHROPIC_IMAGE_BYTES = 4_900_000


def get_anthropic_key_status() -> dict:
    """Check API key presence/format without calling the API."""
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return {
            "configured": False,
            "looks_valid": False,
            "hint": "ANTHROPIC_API_KEY가 비어 있습니다.",
        }
    if api_key.startswith("your_") or "key_here" in api_key:
        return {
            "configured": True,
            "looks_valid": False,
            "hint": "예시 값(your_anthropic_key_here)입니다. 실제 키로 바꿔 주세요.",
        }
    if not api_key.startswith("sk-ant-"):
        return {
            "configured": True,
            "looks_valid": False,
            "hint": "키 형식이 sk-ant- 로 시작하지 않습니다. Anthropic 콘솔에서 발급한 키인지 확인해 주세요.",
        }
    return {
        "configured": True,
        "looks_valid": True,
        "hint": "키 형식은 정상입니다. 오류가 계속되면 키 재발급·결제 상태를 확인해 주세요.",
    }


def _validate_api_key() -> str:
    status = get_anthropic_key_status()
    if not status["configured"]:
        raise ValueError(
            "ANTHROPIC_API_KEY가 비어 있습니다. backend/.env 파일에 API 키를 입력해 주세요."
        )
    if not status["looks_valid"]:
        raise ValueError(
            f"{status['hint']} (backend/.env 수정 후 서버를 완전히 재시작해 주세요.)"
        )
    return (os.getenv("ANTHROPIC_API_KEY") or "").strip()


def _sanitize_feedback(text: str) -> str:
    """Remove markdown bold markers the model must not emit."""
    return text.replace("**", "")


def _resolve_image_path(image_path: str) -> Path:
    return resolve_upload_file_path(image_path)


def _fit_image(img: Image.Image, max_side: int) -> Image.Image:
    width, height = img.size
    longest = max(width, height)
    if longest <= max_side:
        return img
    scale = max_side / longest
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return img.resize(new_size, Image.Resampling.LANCZOS)


def _to_rgb_image(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        return background
    if img.mode == "P":
        return img.convert("RGBA").convert("RGB")
    return img.convert("RGB")


def encode_image_for_api(image_path: str) -> tuple[bytes, str]:
    """Return image bytes and media type, compressing when over Anthropic's 5MB limit."""
    image_path_obj = _resolve_image_path(image_path)
    raw = image_path_obj.read_bytes()
    ext = image_path_obj.suffix.lower()
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }

    if len(raw) <= MAX_ANTHROPIC_IMAGE_BYTES:
        return raw, media_type_map.get(ext, "image/jpeg")

    logger.info(
        "Compressing image for Claude API: %s (%s bytes)",
        image_path_obj.name,
        len(raw),
    )

    with Image.open(io.BytesIO(raw)) as img:
        if getattr(img, "is_animated", False):
            img.seek(0)
        rgb = _to_rgb_image(img)

        for max_side in (2048, 1600, 1280, 1024, 800, 640):
            resized = _fit_image(rgb, max_side)
            for quality in (85, 75, 65, 55, 45, 35):
                buffer = io.BytesIO()
                resized.save(buffer, format="JPEG", quality=quality, optimize=True)
                data = buffer.getvalue()
                if len(data) <= MAX_ANTHROPIC_IMAGE_BYTES:
                    logger.info(
                        "Compressed %s to %s bytes (%spx, q=%s)",
                        image_path_obj.name,
                        len(data),
                        max_side,
                        quality,
                    )
                    return data, "image/jpeg"

    raise ValueError(
        f"이미지 '{image_path_obj.name}'가 너무 커서 분석할 수 없습니다. "
        "더 작은 사진으로 다시 업로드해 주세요."
    )


def _image_content_block(image_path: str) -> dict:
    image_bytes, media_type = encode_image_for_api(image_path)
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": image_data,
        },
    }


def generate_feedback(
    image_path: str | list[str],
    level_key: str,
    stage_num: int,
    extra_instruction: str = "",
    previous_feedbacks: list = None,
) -> str:
    """
    Generate writing feedback using Claude vision.

    Registration names are never passed to the model (privacy).
    """
    api_key = _validate_api_key()
    client = anthropic.Anthropic(api_key=api_key)

    image_paths = image_path if isinstance(image_path, list) else [image_path]
    if not image_paths:
        raise FileNotFoundError("No image files provided")

    user_prompt = get_feedback_user_prompt(
        level_key=level_key,
        stage_num=stage_num,
        extra_instruction=extra_instruction,
        previous_feedbacks=previous_feedbacks or [],
    )
    content_blocks = [_image_content_block(path) for path in image_paths]
    content_blocks.append({
        "type": "text",
        "text": user_prompt,
    })

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=get_system_prompt(),
            messages=[
                {
                    "role": "user",
                    "content": content_blocks,
                }
            ],
        )
    except anthropic.AuthenticationError as e:
        raise ValueError(
            "Anthropic가 API 키를 거부했습니다. "
            "1) console.anthropic.com 에서 새 키 발급 "
            "2) backend/.env 한 줄에 ANTHROPIC_API_KEY=sk-ant-... (따옴표 없이) "
            "3) 서버 Ctrl+C 후 다시 실행"
        ) from e
    except anthropic.APIStatusError as e:
        if e.status_code == 401:
            raise ValueError(
                "Anthropic 인증 실패(401). API 키를 재발급하고 backend/.env를 수정한 뒤 서버를 재시작해 주세요."
            ) from e
        if e.status_code == 400 and "image exceeds" in str(e):
            raise ValueError(
                "사진 용량이 커서 분석하지 못했습니다. 더 작은 사진으로 다시 업로드해 주세요."
            ) from e
        raise

    return _sanitize_feedback(response.content[0].text)
