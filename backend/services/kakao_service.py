"""
kakao_service.py - Kakao Channel API integration for sending messages to parents
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)


def get_kakao_headers() -> dict:
    """Build authorization headers for Kakao API."""
    token = os.getenv("KAKAO_CHANNEL_TOKEN")
    if not token:
        raise ValueError("KAKAO_CHANNEL_TOKEN environment variable is not set")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def send_message(kakao_user_id: str, message_text: str) -> dict:
    """
    Send a text message to a parent via Kakao Channel (친구톡/알림톡).

    Args:
        kakao_user_id: The Kakao user ID of the parent (from webhook)
        message_text: The feedback text to send

    Returns:
        Response dict with success status and details

    Note:
        Kakao Business Channel API endpoint may vary depending on your setup.
        See: https://developers.kakao.com/docs/latest/ko/message/rest-api
        For production, you may need to use KakaoTalk Channel Message API or
        Kakao i Open Builder's proactive message sending feature.
    """
    # Kakao Channel message API endpoint
    # TODO: Replace with actual endpoint based on your Kakao Business setup
    # Option 1: KakaoTalk Channel (친구톡) - requires Channel subscription
    # Option 2: Kakao i Open Builder proactive message API
    kakao_api_base = os.getenv(
        "KAKAO_API_BASE_URL", "https://kapi.kakao.com"
    )
    endpoint = f"{kakao_api_base}/v1/api/talk/channels/message/send"

    headers = get_kakao_headers()

    payload = {
        "receiver_uuids": [kakao_user_id],
        "template_object": {
            "object_type": "text",
            "text": message_text,
            "link": {},
        },
    }

    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        result = response.json()
        logger.info(f"Message sent to {kakao_user_id}: {result}")
        return {"success": True, "response": result}
    except requests.exceptions.HTTPError as e:
        logger.error(f"Kakao API HTTP error for user {kakao_user_id}: {e}")
        logger.error(f"Response body: {e.response.text if e.response else 'N/A'}")
        return {
            "success": False,
            "error": str(e),
            "response_body": e.response.text if e.response else None,
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Kakao API request failed for user {kakao_user_id}: {e}")
        return {"success": False, "error": str(e)}


def send_feedback_message(kakao_user_id: str, child_name: str, feedback_text: str) -> dict:
    """
    Send a formatted feedback message to a parent.

    Args:
        kakao_user_id: The Kakao user ID of the parent
        child_name: The child's name for the message greeting
        feedback_text: The generated feedback text

    Returns:
        Response dict with success status
    """
    message = f"안녕하세요! 예진샘이에요 😊\n\n{child_name} 친구의 글쓰기 피드백을 보내드려요.\n\n{feedback_text}\n\n다음 글쓰기도 기대할게요! 화이팅! 🌟"
    return send_message(kakao_user_id, message)


def build_kakao_response(text: str) -> dict:
    """
    Build a valid Kakao i Open Builder webhook response.

    Args:
        text: Text to send back to the user

    Returns:
        Properly formatted Kakao response dict
    """
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": text,
                    }
                }
            ]
        },
    }
