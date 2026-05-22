"""
parent_match.py - Match Kakao channel users to pre-registered parents (admin-linked botUserKey).
"""

import logging

from sqlalchemy.orm import Session

from database import Parent

logger = logging.getLogger(__name__)

PENDING_KAKAO_PREFIX = "pending:"

CHANNEL_GREETING = "생글방글입니다. 문의 사항이 있으시면 남겨주세요 :)"
GUEST_CHILD_NAME = "채널 미등록"

IMAGE_UTTERANCE_MARKERS = (
    "이미지",
    "사진",
    "photo",
    "image",
)


def pending_kakao_user_id(phone_number: str) -> str:
    return f"{PENDING_KAKAO_PREFIX}{phone_number}"


def is_pending_kakao_user_id(kakao_user_id: str | None) -> bool:
    return bool(kakao_user_id and kakao_user_id.startswith(PENDING_KAKAO_PREFIX))


def resolve_parent(db: Session, bot_user_key: str) -> Parent | None:
    """Find parent by Kakao botUserKey set in the admin (no in-chat phone linking)."""
    if not bot_user_key:
        return None
    return db.query(Parent).filter(Parent.kakao_user_id == bot_user_key).first()


def looks_like_image_only_utterance(utterance: str) -> bool:
    """Kakao may show 'N장의 이미지를 보냈어요' without secureimage URLs in the skill payload."""
    normalized = (utterance or "").replace(" ", "").lower()
    return any(marker in normalized for marker in IMAGE_UTTERANCE_MARKERS)


def get_or_create_guest_parent(db: Session, bot_user_key: str) -> Parent:
    """First-time channel visitor with a real image URL — save under a placeholder parent."""
    existing = resolve_parent(db, bot_user_key)
    if existing:
        return existing

    parent = Parent(
        kakao_user_id=bot_user_key,
        phone_number=None,
        child_name=GUEST_CHILD_NAME,
        child_age=None,
        level="표현력",
    )
    db.add(parent)
    db.commit()
    db.refresh(parent)
    logger.info(
        "Auto-created guest parent id=%s for bot_user_key=%s (assign phone in admin)",
        parent.id,
        bot_user_key,
    )
    return parent
