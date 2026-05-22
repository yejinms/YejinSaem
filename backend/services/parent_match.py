"""
parent_match.py - Match Kakao channel users to pre-registered parents (admin-linked botUserKey).
"""

from sqlalchemy.orm import Session

from database import Parent

PENDING_KAKAO_PREFIX = "pending:"

CHANNEL_GREETING = "생글방글입니다. 문의 사항이 있으시면 남겨주세요 :)"


def pending_kakao_user_id(phone_number: str) -> str:
    return f"{PENDING_KAKAO_PREFIX}{phone_number}"


def is_pending_kakao_user_id(kakao_user_id: str | None) -> bool:
    return bool(kakao_user_id and kakao_user_id.startswith(PENDING_KAKAO_PREFIX))


def resolve_parent(db: Session, bot_user_key: str) -> Parent | None:
    """Find parent by Kakao botUserKey set in the admin (no in-chat phone linking)."""
    if not bot_user_key:
        return None
    return db.query(Parent).filter(Parent.kakao_user_id == bot_user_key).first()
