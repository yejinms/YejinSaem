"""
admin.py - Admin REST API for managing submissions and parents
"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

from database import Parent, Submission, get_db
from datetime_utils import to_utc_iso
from levels_utils import apply_parent_levels, parent_levels_for_api, resolve_levels_input
from mission_history import get_last_selected_mission
from parent_import import import_parents_from_text
from services.claude_service import generate_feedback, get_anthropic_key_status
from services.outbound_privacy import sanitize_channel_feedback
from services.kakao_service import send_feedback_message
from services.parent_match import is_pending_kakao_user_id, pending_kakao_user_id
from upload_paths import resolve_upload_file_path
from validation import (
    normalize_phone_number,
    read_validated_upload,
    validate_child_age,
    validate_level,
    validate_levels,
    verify_admin,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(verify_admin)])

MAX_SUBMISSION_IMAGES = 10


@router.get("/config-status")
def admin_config_status():
    """API 키 설정 상태 확인 (키 값은 노출하지 않음)."""
    backend_dir = Path(__file__).resolve().parent.parent
    env_path = backend_dir / ".env"
    return {
        "env_file": str(env_path),
        "env_file_exists": env_path.is_file(),
        "anthropic": get_anthropic_key_status(),
    }


# ---------- Pydantic Schemas ----------

class GenerateFeedbackRequest(BaseModel):
    level: str
    stage: int
    extra_instruction: Optional[str] = ""


class ApproveRequest(BaseModel):
    feedback_text: Optional[str] = None  # If provided, overrides the stored draft


class ParentCreate(BaseModel):
    kakao_user_id: Optional[str] = None
    phone_number: str
    child_name: str
    child_age: Optional[int] = None
    level: Optional[str] = "표현력"
    levels: Optional[list[str]] = None


class ParentUpdate(BaseModel):
    phone_number: Optional[str] = None
    kakao_user_id: Optional[str] = None
    child_name: Optional[str] = None
    child_age: Optional[int] = None
    level: Optional[str] = None
    levels: Optional[list[str]] = None


class ParentBulkImportRequest(BaseModel):
    text: str
    channel_filter: Optional[str] = None


def serialize_parent(parent: Parent) -> dict:
    levels = parent_levels_for_api(parent)
    return {
        "id": parent.id,
        "kakao_user_id": parent.kakao_user_id,
        "phone_number": parent.phone_number,
        "child_name": parent.child_name,
        "child_age": parent.child_age,
        "level": parent.level,
        "levels": levels,
        "created_at": to_utc_iso(parent.created_at),
    }


def get_submission_photo_paths(submission: Submission) -> list[str]:
    if not submission.photo_path:
        return []

    raw_path = submission.photo_path.strip()
    if not raw_path.startswith("["):
        return [submission.photo_path]

    try:
        paths = json.loads(raw_path)
    except json.JSONDecodeError:
        return [submission.photo_path]

    if not isinstance(paths, list):
        return []
    return [path for path in paths if isinstance(path, str) and path]


def serialize_photo_paths(paths: list[str]) -> str | None:
    if not paths:
        return None
    if len(paths) == 1:
        return paths[0]
    return json.dumps(paths, ensure_ascii=False)


def serialize_submission(
    submission: Submission,
    include_parent_created_at: bool = False,
    last_selected_mission: dict | None = None,
) -> dict:
    parent = submission.parent
    parent_payload = None
    if parent:
        parent_payload = {
            "id": parent.id,
            "kakao_user_id": parent.kakao_user_id,
            "phone_number": parent.phone_number,
            "child_name": parent.child_name,
            "child_age": parent.child_age,
            "level": parent.level,
            "levels": parent_levels_for_api(parent),
        }
        if include_parent_created_at:
            parent_payload["created_at"] = to_utc_iso(parent.created_at)

    photo_paths = get_submission_photo_paths(submission)
    payload = {
        "id": submission.id,
        "status": submission.status,
        "photo_path": photo_paths[0] if photo_paths else None,
        "photo_paths": photo_paths,
        "level": submission.level,
        "stage": submission.stage,
        "extra_instruction": submission.extra_instruction,
        "feedback_draft": submission.feedback_draft,
        "created_at": to_utc_iso(submission.created_at),
        "updated_at": to_utc_iso(submission.updated_at),
        "parent": parent_payload,
    }
    if last_selected_mission is not None:
        payload["last_selected_mission"] = last_selected_mission
    return payload


def send_submission_feedback(submission: Submission, feedback_text: str, db: Session) -> dict:
    parent = submission.parent
    if not parent:
        raise HTTPException(status_code=400, detail="Submission has no associated parent")

    final_feedback = feedback_text or submission.feedback_draft
    if not final_feedback:
        raise HTTPException(
            status_code=400,
            detail="No feedback text available. Generate feedback first.",
        )

    if not parent.phone_number:
        raise HTTPException(
            status_code=400,
            detail="학부모 전화번호가 등록되지 않았습니다. 학부모 정보에서 전화번호를 먼저 등록해주세요.",
        )

    try:
        safe_feedback = sanitize_channel_feedback(final_feedback, parent)
        result = send_feedback_message(
            phone_number=parent.phone_number,
            feedback_text=safe_feedback,
        )
    except Exception as e:
        logger.error(f"Kakao send raised for submission {submission.id}: {e}")
        result = {"success": False, "error": str(e)}

    submission.feedback_draft = final_feedback
    if result.get("success"):
        submission.status = "sent"
        db.commit()
        return {
            "id": submission.id,
            "status": "sent",
            "message": "피드백이 성공적으로 전송되었습니다.",
            "kakao_response": result.get("response"),
        }

    submission.status = "approved"
    db.commit()
    logger.error(f"Kakao send failed for submission {submission.id}: {result.get('error')}")
    detail = f"피드백은 저장되었지만 카카오 전송에 실패했습니다: {result.get('error')}"
    if result.get("response_body"):
        detail += f" ({result['response_body'][:200]})"
    raise HTTPException(status_code=502, detail=detail)


# ---------- Submission endpoints ----------

@router.post("/submissions/upload", status_code=status.HTTP_201_CREATED)
async def upload_submission(
    parent_id: int,
    photos: Optional[list[UploadFile]] = File(default=None),
    photo: Optional[UploadFile] = File(default=None),
    db: Session = Depends(get_db),
):
    """관리자가 직접 학부모 사진을 업로드해서 제출 생성."""
    parent = db.query(Parent).filter(Parent.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="학부모를 찾을 수 없습니다")

    upload_files = list(photos or [])
    if photo is not None:
        upload_files.append(photo)

    if not upload_files:
        raise HTTPException(status_code=400, detail="이미지를 1장 이상 업로드해주세요.")
    if len(upload_files) > MAX_SUBMISSION_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"이미지는 최대 {MAX_SUBMISSION_IMAGES}장까지 업로드할 수 있습니다.",
        )

    validated_uploads = []
    for upload in upload_files:
        content, ext = await read_validated_upload(upload)
        validated_uploads.append((content, ext))

    photo_paths = []
    for content, ext in validated_uploads:
        filename = f"{uuid.uuid4().hex}{ext}"
        dest = UPLOAD_DIR / filename
        dest.write_bytes(content)
        photo_paths.append(str(dest))

    submission = Submission(
        parent_id=parent_id,
        photo_path=serialize_photo_paths(photo_paths),
        level=parent.level,
        status="pending",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return {
        "id": submission.id,
        "photo_path": photo_paths[0],
        "photo_paths": photo_paths,
        "status": "pending",
        "created_at": to_utc_iso(submission.created_at),
    }


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

    return [serialize_submission(s) for s in submissions]


@router.get("/submissions/{submission_id}")
def get_submission(submission_id: int, db: Session = Depends(get_db)):
    """Get a single submission with full detail."""
    s = db.query(Submission).filter(Submission.id == submission_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Submission not found")

    last_mission = None
    if s.parent_id:
        last_mission = get_last_selected_mission(db, s.parent_id, s.id)
    return serialize_submission(
        s,
        include_parent_created_at=True,
        last_selected_mission=last_mission,
    )


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

    photo_paths = get_submission_photo_paths(s)
    if not photo_paths:
        raise HTTPException(status_code=400, detail="No photo attached to this submission")

    parent = s.parent
    if not parent:
        raise HTTPException(status_code=400, detail="Submission has no associated parent")

    validate_level(body.level)
    if not (1 <= body.stage <= 10):
        raise HTTPException(status_code=400, detail="Stage must be between 1 and 10")

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
        feedback_text = sanitize_channel_feedback(
            generate_feedback(
                image_path=photo_paths,
                level_key=body.level,
                stage_num=body.stage,
                extra_instruction=body.extra_instruction or "",
                previous_feedbacks=previous_feedbacks,
            ),
            parent,
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


@router.delete("/submissions/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_submission(submission_id: int, db: Session = Depends(get_db)):
    """Delete a single submission and its uploaded photos."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    delete_submission_files(submission)
    db.delete(submission)
    db.commit()


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

    return send_submission_feedback(s, body.feedback_text or s.feedback_draft, db)


@router.post("/submissions/{submission_id}/retry-send")
def retry_send_submission(
    submission_id: int,
    body: ApproveRequest,
    db: Session = Depends(get_db),
):
    """Retry sending already generated or approved feedback."""
    s = db.query(Submission).filter(Submission.id == submission_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Submission not found")

    if s.status == "sent":
        raise HTTPException(status_code=400, detail="이미 전송된 피드백입니다.")

    return send_submission_feedback(s, body.feedback_text or s.feedback_draft, db)


@router.post("/submissions/{submission_id}/mark-sent")
def mark_submission_sent_manually(
    submission_id: int,
    body: ApproveRequest,
    db: Session = Depends(get_db),
):
    """Mark feedback as sent without calling Solapi (e.g. sent manually in Kakao)."""
    s = db.query(Submission).filter(Submission.id == submission_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Submission not found")

    if s.status == "sent":
        raise HTTPException(status_code=400, detail="이미 전송 완료 처리된 피드백입니다.")

    final_feedback = (body.feedback_text or s.feedback_draft or "").strip()
    if not final_feedback:
        raise HTTPException(status_code=400, detail="피드백 내용을 입력해주세요.")

    s.feedback_draft = final_feedback
    s.status = "sent"
    db.commit()
    db.refresh(s)

    return {
        "id": s.id,
        "status": "sent",
        "message": "직접 전송 완료로 처리되었습니다.",
    }


# ---------- Parent endpoints ----------

@router.get("/parents")
def list_parents(db: Session = Depends(get_db)):
    """List all registered parents."""
    parents = db.query(Parent).order_by(Parent.created_at.desc()).all()
    return [
        {
            "id": p.id,
            "kakao_user_id": p.kakao_user_id,
            "phone_number": p.phone_number,
            "child_name": p.child_name,
            "child_age": p.child_age,
            "level": p.level,
            "levels": parent_levels_for_api(p),
            "created_at": to_utc_iso(p.created_at),
            "submission_count": len(p.submissions),
        }
        for p in parents
    ]


@router.post("/parents", status_code=status.HTTP_201_CREATED)
def create_or_update_parent(body: ParentCreate, db: Session = Depends(get_db)):
    """Create or update a parent by phone number (Kakao botUserKey is linked in admin)."""
    resolved_levels = validate_levels(resolve_levels_input(body.levels, body.level))
    validate_child_age(body.child_age)
    phone_number = normalize_phone_number(body.phone_number, required=True)

    manual_kakao = (body.kakao_user_id or "").strip()
    existing = db.query(Parent).filter(Parent.phone_number == phone_number).first()

    if existing:
        existing.child_name = body.child_name
        existing.child_age = body.child_age
        existing.phone_number = phone_number
        apply_parent_levels(existing, resolved_levels)
        if manual_kakao:
            existing.kakao_user_id = manual_kakao
        db.commit()
        db.refresh(existing)
        parent = existing
        created = False
    else:
        kakao_user_id = manual_kakao or pending_kakao_user_id(phone_number)
        parent = Parent(
            kakao_user_id=kakao_user_id,
            phone_number=phone_number,
            child_name=body.child_name,
            child_age=body.child_age,
            level=resolved_levels[0],
        )
        apply_parent_levels(parent, resolved_levels)
        db.add(parent)
        db.commit()
        db.refresh(parent)
        created = True

    response = serialize_parent(parent)
    response["created"] = created
    response["kakao_linked"] = not is_pending_kakao_user_id(parent.kakao_user_id)
    return response


@router.post("/parents/bulk-import")
def bulk_import_parents(body: ParentBulkImportRequest, db: Session = Depends(get_db)):
    """Import parents from tab-separated spreadsheet paste."""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="붙여넣을 데이터가 없습니다.")

    result = import_parents_from_text(
        db,
        text,
        channel_filter=(body.channel_filter or "").strip() or None,
    )
    if result["created"] == 0 and result["skipped"] == 0 and result["errors"]:
        raise HTTPException(
            status_code=400,
            detail={"message": "가져올 수 있는 행이 없습니다.", "errors": result["errors"]},
        )
    return result


@router.get("/parents/{parent_id}")
def get_parent(parent_id: int, db: Session = Depends(get_db)):
    """Get a single parent's details."""
    parent = db.query(Parent).filter(Parent.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")

    return serialize_parent(parent)


@router.put("/parents/{parent_id}")
def update_parent(parent_id: int, body: ParentUpdate, db: Session = Depends(get_db)):
    """Update a parent's information."""
    parent = db.query(Parent).filter(Parent.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")

    if body.child_name is not None:
        if not body.child_name.strip():
            raise HTTPException(status_code=400, detail="아이 이름을 입력해주세요.")
        parent.child_name = body.child_name
    if body.phone_number is not None:
        parent.phone_number = normalize_phone_number(body.phone_number)
    if body.kakao_user_id is not None:
        manual_kakao = body.kakao_user_id.strip()
        if manual_kakao:
            parent.kakao_user_id = manual_kakao
    if body.child_age is not None:
        validate_child_age(body.child_age)
        parent.child_age = body.child_age
    if body.levels is not None:
        apply_parent_levels(parent, validate_levels(body.levels))
    elif body.level is not None:
        validate_level(body.level)
        apply_parent_levels(parent, [body.level])

    db.commit()
    db.refresh(parent)

    return serialize_parent(parent)


def delete_submission_files(submission: Submission) -> None:
    for stored_path in get_submission_photo_paths(submission):
        try:
            file_path = resolve_upload_file_path(stored_path)
            file_path.unlink()
        except FileNotFoundError:
            logger.warning("Upload file already missing: %s", stored_path)
        except OSError as e:
            logger.warning("Failed to delete upload %s: %s", stored_path, e)


@router.delete("/parents/{parent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_parent(parent_id: int, db: Session = Depends(get_db)):
    """Delete a parent and all associated submissions."""
    parent = db.query(Parent).filter(Parent.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")

    submissions = db.query(Submission).filter(Submission.parent_id == parent_id).all()
    for submission in submissions:
        delete_submission_files(submission)
        db.delete(submission)

    db.delete(parent)
    db.commit()


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
            "phone_number": parent.phone_number,
            "level": parent.level,
            "levels": parent_levels_for_api(parent),
        },
        "submissions": [
            {
                "id": s.id,
                "status": s.status,
                "level": s.level,
                "stage": s.stage,
                "feedback_draft": s.feedback_draft,
                "photo_path": serialize_submission(s)["photo_path"],
                "photo_paths": serialize_submission(s)["photo_paths"],
                "created_at": to_utc_iso(s.created_at),
            }
            for s in submissions
        ],
    }
