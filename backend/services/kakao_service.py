"""
kakao_service.py - Solapi를 통한 카카오 친구톡 발송
"""

import hashlib
import hmac
import logging
import os
import uuid
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

SOLAPI_API_URL = "https://api.solapi.com/messages/v4/send"
SOLAPI_CHANNELS_URL = "https://api.solapi.com/kakao/v2/channels"

_pf_id_cache: str | None = None


def _auth_headers() -> dict:
    api_key = os.getenv("SOLAPI_API_KEY")
    api_secret = os.getenv("SOLAPI_API_SECRET")
    if not api_key or not api_secret:
        raise ValueError("SOLAPI_API_KEY 또는 SOLAPI_API_SECRET 환경변수가 설정되지 않았습니다")

    date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    salt = str(uuid.uuid4()).replace("-", "")
    signature_str = date + salt
    signature = hmac.new(
        api_secret.encode("utf-8"),
        signature_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return {
        "Authorization": (
            f"HMAC-SHA256 apiKey={api_key}, date={date}, salt={salt}, signature={signature}"
        ),
        "Content-Type": "application/json",
    }


def _resolve_pf_id() -> str:
    """카카오 채널 pfId (KA01PF...). SOLAPI_PF_ID 우선, 없으면 API로 조회."""
    global _pf_id_cache

    pf_id = os.getenv("SOLAPI_PF_ID", "").strip()
    if pf_id:
        return pf_id

    legacy = os.getenv("SOLAPI_SENDER_KEY", "").strip()
    if legacy.startswith("KA"):
        return legacy

    if _pf_id_cache:
        return _pf_id_cache

    response = requests.get(
        SOLAPI_CHANNELS_URL,
        headers=_auth_headers(),
        timeout=10,
    )
    response.raise_for_status()
    channels = response.json().get("channelList", [])
    if not channels:
        raise ValueError(
            "연동된 카카오 채널이 없습니다. 솔라피 콘솔에서 채널을 연동하거나 "
            "SOLAPI_PF_ID를 .env에 설정해 주세요."
        )

    _pf_id_cache = channels[0]["channelId"]
    logger.info("Solapi pfId 자동 조회: %s (%s)", _pf_id_cache, channels[0].get("channelName"))
    return _pf_id_cache


def send_message(phone_number: str, message_text: str) -> dict:
    """솔라피 친구톡(CTA) API로 학부모에게 메시지 발송."""
    sender_phone = os.getenv("SOLAPI_SENDER_PHONE")
    if not sender_phone:
        raise ValueError("SOLAPI_SENDER_PHONE 환경변수가 설정되지 않았습니다")

    pf_id = _resolve_pf_id()
    payload = {
        "message": {
            "to": phone_number,
            "from": sender_phone,
            "type": "CTA",
            "kakaoOptions": {
                "pfId": pf_id,
                "adFlag": False,
                "disableSms": True,
            },
            "text": message_text,
        }
    }

    try:
        response = requests.post(
            SOLAPI_API_URL,
            json=payload,
            headers=_auth_headers(),
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()
        logger.info("친구톡 발송 완료 → %s: %s", phone_number, result)
        return {"success": True, "response": result}
    except requests.exceptions.HTTPError as e:
        body = e.response.text if e.response is not None else "N/A"
        logger.error("솔라피 HTTP 오류 → %s: %s | %s", phone_number, e, body)
        return {"success": False, "error": str(e), "response_body": body}
    except requests.exceptions.RequestException as e:
        logger.error("솔라피 요청 실패 → %s: %s", phone_number, e)
        return {"success": False, "error": str(e)}


def send_feedback_message(phone_number: str, child_name: str, feedback_text: str) -> dict:
    """학부모에게 피드백 전송. child_name은 API 호환용이며 메시지에는 넣지 않음."""
    del child_name
    message = (
        f"{feedback_text}\n\n"
    )
    return send_message(phone_number, message)


def build_kakao_response(text: str) -> dict:
    return {
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": text}}]
        },
    }
