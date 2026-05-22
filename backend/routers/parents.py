"""
parents.py - Parent/child management endpoints (public-facing, no auth required)
These are lighter-weight endpoints that parents or a self-service flow could use.
Admin-level CRUD is in admin.py.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Parent, Submission, get_db
from datetime_utils import to_utc_iso

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/parents", tags=["parents"])


class ParentRegistration(BaseModel):
    kakao_user_id: str
    child_name: str
    child_age: int
    level: str = "표현력"


@router.get("/{kakao_user_id}/profile")
def get_parent_profile(kakao_user_id: str, db: Session = Depends(get_db)):
    """Get a parent's profile by their Kakao user ID."""
    parent = db.query(Parent).filter(Parent.kakao_user_id == kakao_user_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="등록된 학부모 정보가 없습니다.")

    return {
        "id": parent.id,
        "child_name": parent.child_name,
        "child_age": parent.child_age,
        "level": parent.level,
        "created_at": to_utc_iso(parent.created_at),
    }


@router.get("/{kakao_user_id}/submissions")
def get_parent_submissions(
    kakao_user_id: str,
    db: Session = Depends(get_db),
    limit: int = 10,
):
    """Get recent submissions for a parent by their Kakao user ID."""
    parent = db.query(Parent).filter(Parent.kakao_user_id == kakao_user_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="등록된 학부모 정보가 없습니다.")

    submissions = (
        db.query(Submission)
        .filter(Submission.parent_id == parent.id)
        .order_by(Submission.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": s.id,
            "status": s.status,
            "level": s.level,
            "stage": s.stage,
            "created_at": to_utc_iso(s.created_at),
            # Only show feedback if it's been sent
            "feedback": s.feedback_draft if s.status == "sent" else None,
        }
        for s in submissions
    ]
