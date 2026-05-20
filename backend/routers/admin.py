"""
admin.py - Admin REST API for managing submissions and parents
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Parent, Submission, get_db
from services.claude_service import generate_feedback
from services.kakao_service import send_feedback_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------- Pydantic Schemas ----------

class GenerateFeedbackRequest(BaseModel):
    level: str
    stage: int
    extra_instruction: Optional[str] = ""


class ApproveRequest(BaseModel):
    feedback_text: Optional[str] = None  # If provided, overrides the stored draft


class ParentCreate(BaseModel):
    kakao_user_id: str
    phone_number: Optional[str] = None
    child_name: str
    child_age: Optional[int] = None
    level: str = "표현력"


class ParentUpdate(BaseModel):
    child_name: Optional[str] = None
    child_age: Optional[int] = None
    level: Optional[str] = None


# ---------- Submission endpoints ----------

@router.get("/submissions")
def list_submissions(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List submissions, optionally filtered by status."""
    query = db.query(Submission)
    if status:
        query = query.filter(Submission.status == status)
    submissions = query.order_by(Submission.created_at.desc()).all()

    result = []
    for s in submissions:
        parent = s.parent
        result.append({
            "id": s.id,
            "status": s.status,
            "photo_path": s.photo_path,
            "level": s.level,
            "stage": s.stage,
            "extra_instruction": s.extra_instruction,
            "feedback_draft": s.feedback_draft,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            "parent": {
                "id": parent.id,
                "kakao_user_id": parent.kakao_user_id,
                "child_name": parent.child_name,
                "child_age": parent.child_age,
                "level": parent.level,
            } if parent else None,
        })
    return result


@router.get("/submissions/{submission_id}")
def get_submission(submission_id: int, db: Session = Depends(get_db)):
    """Get a single submission with full detail."""
    s = db.query(Submission).filter(Submission.id == submission_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Submission not found")

    parent = s.parent
    return {
        "id": s.id,
        "status": s.status,
        "photo_path": s.photo_path,
        "level": s.level,
        "stage": s.stage,
        "extra_instruction": s.extra_instruction,
        "feedback_draft": s.feedback_draft,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        "parent": {
            "id": parent.id,
            "kakao_user_id": parent.kakao_user_id,
            "child_name": parent.child_name,
            "child_age": parent.child_age,
            "level": parent.level,
            "created_at": parent.created_at.isoformat() if parent.created_at else None,
        } if parent else None,
    }


@router.post("/submissions/{submission_id}/generate")
def generate_submission_feedback(
    submission_id: int,
    body: GenerateFeedbackRequest,
    db: Session = Depends(get_db),
):
    """Generate Claude AI feedback for a submission."""
    s = db.query(Submission).filter(Submission.id == submission_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Submission not found")

    if not s.photo_path:
        raise HTTPException(status_code=400, detail="No photo attached to this submission")

    parent = s.parent
    if not parent:
        raise HTTPException(status_code=400, detail="Submission has no associated parent")

    # Validate level and stage
    valid_levels = ["표현력", "초등기초", "초등심화"]
    if body.level not in valid_levels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid level. Must be one of: {valid_levels}"
        )
    if not (1 <= body.stage <= 10):
        raise HTTPException(status_code=400, detail="Stage must be between 1 and 10")

    # Get recent feedbacks for this child to avoid repetition
    recent_submissions = (
        db.query(Submission)
        .filter(
            Submission.parent_id == parent.id,
            Submission.feedback_draft.isnot(None),
            Submission.id != submission_id,
        )
        .order_by(Submission.created_at.desc())
        .limit(3)
        .all()
    )
    previous_feedbacks = [rs.feedback_draft for rs in recent_submissions if rs.feedback_draft]

    try:
        feedback_text = generate_feedback(
            image_path=s.photo_path,
            level_key=body.level,
            stage_num=body.stage,
            child_name=parent.child_name,
            extra_instruction=body.extra_instruction or "",
            previous_feedbacks=previous_feedbacks,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Claude API error for submission {submission_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate feedback: {str(e)}")

    # Update submission
    s.level = body.level
    s.stage = body.stage
    s.extra_instruction = body.extra_instruction or s.extra_instruction
    s.feedback_draft = feedback_text
    s.status = "generated"
    db.commit()
    db.refresh(s)

    return {
        "id": s.id,
        "status": s.status,
        "feedback_draft": s.feedback_draft,
        "level": s.level,
        "stage": s.stage,
    }


@router.put("/submissions/{submission_id}/approve")
def approve_and_send_submission(
    submission_id: int,
    body: ApproveRequest,
    db: Session = Depends(get_db),
):
    """Approve feedback (optionally with edits) and send via Kakao."""
    s = db.query(Submission).filter(Submission.id == submission_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Submission not found")

    parent = s.parent
    if not parent:
        raise HTTPException(status_code=400, detail="Submission has no associated parent")

    # Use provided text or the stored draft
    final_feedback = body.feedback_text or s.feedback_draft
    if not final_feedback:
        raise HTTPException(
            status_code=400,
            detail="No feedback text available. Generate feedback first."
        )

    # Send via Kakao
    if not parent.phone_number:
        raise HTTPException(
            status_code=400,
            detail="학부모 전화번호가 등록되지 않았습니다. 학부모 정보에서 전화번호를 먼저 등록해주세요.",
        )
    result = send_feedback_message(
        phone_number=parent.phone_number,
        child_name=parent.child_name,
        feedback_text=final_feedback,
    )

    if result.get("success"):
        s.feedback_draft = final_feedback
        s.status = "sent"
        db.commit()
        return {
            "id": s.id,
            "status": "sent",
            "message": "피드백이 성공적으로 전송되었습니다.",
            "kakao_response": result.get("response"),
        }
    else:
        # Mark as approved even if send failed, so admin can retry
        s.feedback_draft = final_feedback
        s.status = "approved"
        db.commit()
        logger.error(f"Kakao send failed for submission {submission_id}: {result.get('error')}")
        raise HTTPException(
            status_code=502,
            detail=f"피드백은 저장되었지만 카카오 전송에 실패했습니다: {result.get('error')}",
        )


# ---------- Parent endpoints ----------

@router.get("/parents")
def list_parents(db: Session = Depends(get_db)):
    """List all registered parents."""
    parents = db.query(Parent).order_by(Parent.created_at.desc()).all()
    return [
        {
            "id": p.id,
            "kakao_user_id": p.kakao_user_id,
            "child_name": p.child_name,
            "child_age": p.child_age,
            "level": p.level,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "submission_count": len(p.submissions),
        }
        for p in parents
    ]


@router.post("/parents", status_code=status.HTTP_201_CREATED)
def create_or_update_parent(body: ParentCreate, db: Session = Depends(get_db)):
    """Create a new parent or update existing one by kakao_user_id."""
    valid_levels = ["표현력", "초등기초", "초등심화"]
    if body.level not in valid_levels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid level. Must be one of: {valid_levels}"
        )

    existing = db.query(Parent).filter(Parent.kakao_user_id == body.kakao_user_id).first()

    if existing:
        # Update existing parent
        existing.child_name = body.child_name
        existing.child_age = body.child_age
        existing.level = body.level
        db.commit()
        db.refresh(existing)
        parent = existing
        created = False
    else:
        # Create new parent
        parent = Parent(
            kakao_user_id=body.kakao_user_id,
            phone_number=body.phone_number,
            child_name=body.child_name,
            child_age=body.child_age,
            level=body.level,
        )
        db.add(parent)
        db.commit()
        db.refresh(parent)
        created = True

    return {
        "id": parent.id,
        "kakao_user_id": parent.kakao_user_id,
        "child_name": parent.child_name,
        "child_age": parent.child_age,
        "level": parent.level,
        "created_at": parent.created_at.isoformat() if parent.created_at else None,
        "created": created,
    }


@router.get("/parents/{parent_id}")
def get_parent(parent_id: int, db: Session = Depends(get_db)):
    """Get a single parent's details."""
    parent = db.query(Parent).filter(Parent.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")

    return {
        "id": parent.id,
        "kakao_user_id": parent.kakao_user_id,
        "child_name": parent.child_name,
        "child_age": parent.child_age,
        "level": parent.level,
        "created_at": parent.created_at.isoformat() if parent.created_at else None,
    }


@router.put("/parents/{parent_id}")
def update_parent(parent_id: int, body: ParentUpdate, db: Session = Depends(get_db)):
    """Update a parent's information."""
    parent = db.query(Parent).filter(Parent.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")

    if body.child_name is not None:
        parent.child_name = body.child_name
    if body.child_age is not None:
        parent.child_age = body.child_age
    if body.level is not None:
        valid_levels = ["표현력", "초등기초", "초등심화"]
        if body.level not in valid_levels:
            raise HTTPException(status_code=400, detail=f"Invalid level: {body.level}")
        parent.level = body.level

    db.commit()
    db.refresh(parent)

    return {
        "id": parent.id,
        "kakao_user_id": parent.kakao_user_id,
        "child_name": parent.child_name,
        "child_age": parent.child_age,
        "level": parent.level,
    }


@router.get("/parents/{parent_id}/history")
def get_parent_history(
    parent_id: int,
    db: Session = Depends(get_db),
    limit: int = 20,
):
    """Get submission history for a specific parent/child."""
    parent = db.query(Parent).filter(Parent.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")

    submissions = (
        db.query(Submission)
        .filter(Submission.parent_id == parent_id)
        .order_by(Submission.created_at.desc())
        .limit(limit)
        .all()
    )

    return {
        "parent": {
            "id": parent.id,
            "child_name": parent.child_name,
            "child_age": parent.child_age,
            "level": parent.level,
        },
        "submissions": [
            {
                "id": s.id,
                "status": s.status,
                "level": s.level,
                "stage": s.stage,
                "feedback_draft": s.feedback_draft,
                "photo_path": s.photo_path,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in submissions
        ],
    }
