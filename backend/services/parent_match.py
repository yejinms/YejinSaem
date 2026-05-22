"""
parent_match.py - Match Kakao channel users to pre-registered parents by phone number.
"""

import re

from sqlalchemy.orm import Session

from database import Parent

PENDING_KAKAO_PREFIX = "pending:"


def pending_kakao_user_id(phone_number: str) -> str:
    return f"{PENDING_KAKAO_PREFIX}{phone_number}"


def is_pending_kakao_user_id(kakao_user_id: str | None) -> bool:
    return bool(kakao_user_id and kakao_user_id.startswith(PENDING_KAKAO_PREFIX))


def extract_phone_from_text(text: str) -> str | None:
    """Extract a Korean mobile number from free-form chat text."""
    if not text:
        return None

    candidates = re.findall(r"0?1[016789][\d\-\s]{7,12}", text)
    for raw in candidates:
        digits = re.sub(r"\D", "", raw)
        if digits.startswith("82") and len(digits) >= 11:
            digits = "0" + digits[2:]
        if len(digits) == 10 and digits.startswith("10"):
            digits = "0" + digits
        if len(digits) == 11 and digits.startswith("010"):
            return digits
    return None


def _link_bot_to_parent(db: Session, bot_user_key: str, parent: Parent) -> None:
    """Assign this Kakao channel user to a parent; release the key from any other parent."""
    previous = db.query(Parent).filter(Parent.kakao_user_id == bot_user_key).first()
    if previous and previous.id != parent.id:
        if previous.phone_number:
            previous.kakao_user_id = pending_kakao_user_id(previous.phone_number)
        else:
            previous.kakao_user_id = f"{PENDING_KAKAO_PREFIX}unlinked-{previous.id}"

    parent.kakao_user_id = bot_user_key
    db.commit()
    db.refresh(parent)


def resolve_parent(
    db: Session, bot_user_key: str, utterance: str
) -> tuple[Parent | None, str | None, bool]:
    """
    Find or link a parent for this Kakao bot user.

    Returns (parent, user_message, phone_just_linked).
    When user_message is set, the webhook should reply with it.
    """
    phone = extract_phone_from_text(utterance)
    parent = db.query(Parent).filter(Parent.kakao_user_id == bot_user_key).first()

    if parent and phone and parent.phone_number != phone:
        target = db.query(Parent).filter(Parent.phone_number == phone).first()
        if not target:
            return (
                parent,
                "등록된 번호가 아니에요. 선생님께 사전 등록된 휴대폰 번호인지 확인해 주세요.",
                False,
            )
        _link_bot_to_parent(db, bot_user_key, target)
        return target, None, True

    if parent:
        return parent, None, False

    if phone:
        target = db.query(Parent).filter(Parent.phone_number == phone).first()
        if not target:
            return None, (
                "등록된 번호가 아니에요. 선생님께 사전 등록된 휴대폰 번호인지 확인해 주세요."
            ), False
        _link_bot_to_parent(db, bot_user_key, target)
        return target, None, True

    return None, (
        "안녕하세요! 사전 등록된 휴대폰 번호를 입력해 주세요. "
        "(예: 01012345678) 번호 확인 후 사진을 보내시면 피드백을 받을 수 있어요."
    ), False
