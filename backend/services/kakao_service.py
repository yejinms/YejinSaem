"""
kakao_service.py - Solapi를 통한 카카오 친구톡 발송
"""

import hashlib
import hmac
import logging
import os
import time
import uuid

import requests

logger = logging.getLogger(__name__)

SOLAPI_API_URL = "https://api.solapi.com/messages/v4/send"


def _make_auth_header() -> str:
    api_key = os.getenv("SOLAPI_API_KEY")
    api_secret = os.getenv("SOLAPI_API_SECRET")
    if not api_key or not api_secret:
        raise ValueError("SOLAPI_API_KEY 또는 SOLAPI_API_SECRET 환경변수가 설정되지 않았습니다")

    date = str(int(time.time() * 1000))
    salt = str(uuid.uuid4()).replace("-", "")
    signature_str = date + salt
    signature = hmac.new(
        api_secret.encode("utf-8"),
        signature_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return f"HMAC-SHA256 apiKey={api_key}, date={date}, salt={salt}, signature={signature}"


def send_message(kakao_user_id: str, message_text: str) -> dict:
    """
    솔라피 친구톡 API로 학부모에게 메시지 발송.
    kakao_user_id: 카카오 채널 사용자 ID (수신자 전화번호로 대체 필요 — 아래 주석 참고)
    """
    # 솔라피 친구톡은 수신자를 전화번호로 식별함.
    # kakao_user_id 대신 DB에서 학부모 전화번호를 조회해서 넘겨야 함.
    # 이 함수는 routers/admin.py에서 phone_number를 직접 전달하도록 사용됨.
    phone_number = kakao_user_id  # 실제로는 전화번호 전달
    sender_key = os.getenv("SOLAPI_SENDER_KEY")
    sender_phone = os.getenv("SOLAPI_SENDER_PHONE")

    if not sender_key or not sender_phone:
        raise ValueError("SOLAPI_SENDER_KEY 또는 SOLAPI_SENDER_PHONE 환경변수가 설정되지 않았습니다")

    payload = {
        "message": {
            "to": phone_number,
            "from": sender_phone,
            "type": "FT",  # 친구톡 텍스트
            "kakaoOptions": {
                "senderKey": sender_key,
                "templateCode": "",  # 자유 양식 친구톡은 템플릿 코드 불필요
                "buttonName": "",
                "buttonUrl": "",
                "disableSms": False,  # 친구톡 실패 시 SMS로 대체 발송
            },
            "text": message_text,
        }
    }

    try:
        response = requests.post(
            SOLAPI_API_URL,
            json=payload,
            headers={
                "Authorization": _make_auth_header(),
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()
        logger.info(f"친구톡 발송 완료 → {phone_number}: {result}")
        return {"success": True, "response": result}
    except requests.exceptions.HTTPError as e:
        body = e.response.text if e.response else "N/A"
        logger.error(f"솔라피 HTTP 오류 → {phone_number}: {e} | {body}")
        return {"success": False, "error": str(e), "response_body": body}
    except requests.exceptions.RequestException as e:
        logger.error(f"솔라피 요청 실패 → {phone_number}: {e}")
        return {"success": False, "error": str(e)}


def send_feedback_message(phone_number: str, child_name: str, feedback_text: str) -> dict:
    message = (
        f"안녕하세요! 예진샘이에요 😊\n\n"
        f"{child_name} 친구의 글쓰기 피드백을 보내드려요.\n\n"
        f"{feedback_text}\n\n"
        f"다음 글쓰기도 기대할게요! 화이팅! 🌟"
    )
    return send_message(phone_number, message)


def build_kakao_response(text: str) -> dict:
    return {
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": text}}]
        },
    }
