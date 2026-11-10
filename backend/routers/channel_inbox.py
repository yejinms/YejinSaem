"""Conservative intake of Kakao Channel chats from the browser helper."""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import ChannelInboxItem, Parent, Submission, get_db
from datetime_utils import to_utc_iso
from routers.admin import UPLOAD_DIR, MAX_SUBMISSION_IMAGES, serialize_photo_paths
from validation import read_validated_upload, verify_admin

router = APIRouter(prefix="/admin/channel-inbox", tags=["channel-inbox"], dependencies=[Depends(verify_admin)])


class Discovery(BaseModel):
    source_key: str = Field(min_length=3, max_length=250)
    chat_url: str = Field(max_length=500)
    room_name: str = Field(min_length=1, max_length=200)


class ResolveRequest(BaseModel):
    resolved: bool


class FailureRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


def as_dict(item: ChannelInboxItem) -> dict:
    return {
        "id": item.id, "source_key": item.source_key,
        "chat_url": item.chat_url, "room_name": item.room_name,
        "message_text": item.message_text, "category": item.category,
        "status": item.status, "photo_count": item.photo_count,
        "parent_id": item.parent_id, "submission_id": item.submission_id,
        "error": item.error, "created_at": to_utc_iso(item.created_at),
        "updated_at": to_utc_iso(item.updated_at),
    }


@router.get("")
def list_items(db: Session = Depends(get_db)):
    return [as_dict(item) for item in db.query(ChannelInboxItem).order_by(ChannelInboxItem.created_at.desc()).limit(500)]


@router.post("/discover")
def discover(items: list[Discovery], db: Session = Depends(get_db)):
    if len(items) > 100:
        raise HTTPException(status_code=400, detail="한 번에 최대 100개 채팅만 확인할 수 있습니다.")
    result = []
    for item in items:
        if not item.chat_url.startswith("https://business.kakao.com/space/"):
            raise HTTPException(status_code=400, detail="카카오채널 채팅 URL이 아닙니다.")
        row = db.query(ChannelInboxItem).filter_by(source_key=item.source_key).first()
        if not row:
            row = ChannelInboxItem(**item.model_dump(), category="unprocessed", status="open")
            db.add(row)
            db.flush()
        result.append(as_dict(row))
    db.commit()
    return result


@router.post("/{item_id}/fail")
def fail_item(item_id: int, request: FailureRequest, db: Session = Depends(get_db)):
    item = db.query(ChannelInboxItem).filter_by(id=item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="수신 기록을 찾지 못했습니다.")
    if not item.submission_id:
        item.category = "capture_failed"
        item.error = request.reason
        db.commit()
    return as_dict(item)


def find_parent(db: Session, room_name: str, message_text: str) -> tuple[Optional[Parent], str]:
    name = room_name.strip()
    parents = db.query(Parent).all()
    exact = [p for p in parents if p.child_name.strip() == name]
    if len(exact) == 1:
        return exact[0], ""
    if len(exact) > 1:
        return None, "동명이인 고객이 있어 수동 확인이 필요합니다."

    candidates = []
    for p in parents:
        buyer = p.child_name.split("(", 1)[0].strip()
        if buyer and (name == buyer or name.startswith(buyer + " ") or name.startswith(buyer + "(")):
            candidates.append(p)
    if len(candidates) == 1:
        return candidates[0], ""
    if len(candidates) > 1:
        child_matches = [p for p in candidates if "(" in p.child_name and p.child_name.split("(", 1)[1].split(")", 1)[0] in message_text]
        if len(child_matches) == 1:
            return child_matches[0], ""
        return None, "같은 구매자명의 자녀가 여럿입니다. 아이를 수동 확인해 주세요."
    return None, "채팅방명과 일치하는 구매자명을 찾지 못했습니다."


def classify(text: str, photo_count: int) -> tuple[str, str]:
    compact = text.replace(" ", "").replace("\n", "")
    if any(word in compact for word in ("환불", "결제", "배송", "주문", "교환", "취소", "가격", "문의", "오류", "로그인")):
        return "cs", "CS 문의로 보입니다."
    if any(word in compact for word in ("감사합니다", "고맙습니다", "덕분에", "피드백", "후기", "만족")):
        return "feedback", "학부모 피드백으로 보입니다."
    if not photo_count:
        return "no_photo", "사진이 없습니다."
    if not compact:
        return "worksheet", ""
    if not any(word in compact for word in ("단어", "학습지", "첨삭", "글쓰기", "숙제", "과제", "이번주", "보내드립니다")):
        return "review", "사진이 있지만 첨삭 요청인지 확인이 필요합니다."
    return "worksheet", ""


@router.post("/{item_id}/process")
async def process_item(
    item_id: int,
    message_text: str = Form(default=""),
    chat_url: str = Form(default=""),
    photos: Optional[list[UploadFile]] = File(default=None),
    db: Session = Depends(get_db),
):
    item = db.query(ChannelInboxItem).filter_by(id=item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="수신 기록을 찾지 못했습니다.")
    if item.submission_id:
        return as_dict(item)
    if chat_url.startswith("https://business.kakao.com/space/"):
        item.chat_url = chat_url[:500]
    item.message_text = message_text[:5000]
    uploads = list(photos or [])
    item.photo_count = len(uploads)
    category, reason = classify(message_text, len(uploads))
    item.category = category
    if category != "worksheet":
        item.error = reason
        db.commit()
        return as_dict(item)

    parent, reason = find_parent(db, item.room_name, message_text)
    if not parent:
        item.category = "match_failed"
        item.error = reason
        db.commit()
        return as_dict(item)
    item.parent_id = parent.id
    if not parent.weekly_words_enabled or parent.workbook_purchases:
        item.category = "product_review"
        item.error = "고객의 교재 종류 또는 첨삭권을 확인해 주세요."
        db.commit()
        return as_dict(item)
    if len(uploads) > MAX_SUBMISSION_IMAGES:
        item.category = "upload_failed"
        item.error = f"사진이 {MAX_SUBMISSION_IMAGES}장을 넘습니다."
        db.commit()
        return as_dict(item)

    paths: list[Path] = []
    try:
        validated = [await read_validated_upload(upload) for upload in uploads]
        for content, ext in validated:
            path = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
            path.write_bytes(content)
            paths.append(path)
        submission = Submission(
            parent_id=parent.id, product_type="weekly_words",
            photo_path=serialize_photo_paths([str(path) for path in paths]),
            level=parent.level, status="pending",
        )
        db.add(submission)
        db.flush()
        item.submission_id = submission.id
        item.category = "transferred"
        item.error = None
        db.commit()
    except Exception as exc:
        db.rollback()
        for path in paths:
            path.unlink(missing_ok=True)
        item = db.query(ChannelInboxItem).filter_by(id=item_id).first()
        item.category = "upload_failed"
        item.error = str(exc)[:500]
        db.commit()
    return as_dict(item)


@router.put("/{item_id}/resolve")
def resolve_item(item_id: int, request: ResolveRequest, db: Session = Depends(get_db)):
    item = db.query(ChannelInboxItem).filter_by(id=item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="수신 기록을 찾지 못했습니다.")
    item.status = "resolved" if request.resolved else "open"
    db.commit()
    return as_dict(item)
