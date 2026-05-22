"""
claude_service.py - Claude AI integration for generating writing feedback
"""

import base64
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from prompts import get_feedback_user_prompt, get_system_prompt

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


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


def generate_feedback(
    image_path: str,
    level_key: str,
    stage_num: int,
    child_name: str,
    extra_instruction: str = "",
    previous_feedbacks: list = None,
) -> str:
    """
    Generate writing feedback using Claude vision.
    """
    api_key = _validate_api_key()
    client = anthropic.Anthropic(api_key=api_key)

    image_path_obj = Path(image_path)
    if not image_path_obj.is_file():
        image_path_obj = BACKEND_DIR / image_path
    if not image_path_obj.is_file():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    with open(image_path_obj, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    ext = image_path_obj.suffix.lower()
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_type_map.get(ext, "image/jpeg")

    user_prompt = get_feedback_user_prompt(
        level_key=level_key,
        stage_num=stage_num,
        child_name=child_name,
        extra_instruction=extra_instruction,
        previous_feedbacks=previous_feedbacks or [],
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=get_system_prompt(),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": user_prompt,
                        },
                    ],
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
        raise

    return response.content[0].text
