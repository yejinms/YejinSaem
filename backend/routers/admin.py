"""
admin.py - Admin REST API for managing submissions and parents
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

from database import Parent, Submission, WorkbookPurchase, WorkbookUse, get_db
from datetime_utils import to_utc_iso
from levels_utils import apply_parent_levels, parent_levels_for_api, resolve_levels_input
from mission_history import get_last_selected_mission
from parent_import import import_parents_from_text
from storage_maintenance import (
    cleanup_storage,
    create_photos_backup_zip,
    database_file_path,
    get_storage_status,
)
from storage_r2_archive import request_archive_check, archive_status
from services.claude_service import generate_feedback, get_anthropic_key_status
from services.outbound_privacy import sanitize_channel_feedback
from services.kakao_service import send_feedback_message
from services.parent_match import is_pending_kakao_user_id, pending_kakao_user_id
from upload_paths import (
    delete_submission_photo_files,
    get_submission_photo_paths,
    resolve_upload_file_path,
)
from validation import (
    normalize_phone_number,
    read_validated_upload,
    validate_child_age,
    validate_level,
    validate_levels,
    verify_admin,
)
from workbook_service import (
    PRODUCT_WEEKLY, PRODUCT_WORKBOOK, WORKBOOK_LEVELS,
    active_purchase, import_purchase_rows, parse_purchase_rows,
    purchase_balance, purchase_used, record_use, rework_purchase, seoul_date,
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
    level: Optional[str] = None
    stage: Optional[int] = None
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


class WorkbookImportRequest(BaseModel):
    text: str


class StorageCleanupRequest(BaseModel):
    remove_sent_photos: bool = True
    remove_orphans: bool = True
    vacuum_database: bool = True


def serialize_parent(parent: Parent) -> dict:
    levels = parent_levels_for_api(parent)
    return {
        "id": parent.id,
        "kakao_user_id": parent.kakao_user_id,
        "phone_number": parent.phone_number,
        "child_name": parent.child_name,
        "child_age": parent.child_age,
        "weekly_words_enabled": parent.weekly_words_enabled,
        "level": parent.level,
        "levels": levels,
        "created_at": to_utc_iso(parent.created_at),
        "workbook_purchases": [purchase_balance(p) for p in parent.workbook_purchases],
    }


def get_submission_photo_paths(submission: Submission) -> list[str]:
    from upload_paths import get_submission_photo_paths as _get_paths

    return _get_paths(submission)


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
            "workbook_purchases": [purchase_balance(p) for p in parent.workbook_purchases],
        }
        if include_parent_created_at:
            parent_payload["created_at"] = to_utc_iso(parent.created_at)

    photo_paths = get_submission_photo_paths(submission)
    payload = {
        "id": submission.id,
        "status": submission.status,
        "product_type": submission.product_type or PRODUCT_WEEKLY,
        "workbook_level": submission.workbook_level,
        "rework_of_submission_id": submission.rework_of_submission_id,
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
    if submission.status == "sent":
        raise HTTPException(status_code=409, detail="이미 전송 완료된 피드백입니다.")
    if submission.product_type == PRODUCT_WORKBOOK:
        received_on = seoul_date(submission.created_at)
        available = (
            rework_purchase(db, parent.id, submission.workbook_level,
                            submission.rework_of_submission_id, received_on)
            if submission.rework_of_submission_id else
            active_purchase(db, parent.id, on_date=received_on,
                            workbook_level=submission.workbook_level)
        )
        if not available:
            raise HTTPException(status_code=409, detail="사용 가능한 8주 완성 첨삭권이 없습니다.")

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
        if submission.product_type == PRODUCT_WORKBOOK and not submission.rework_of_submission_id:
            record_use(db, submission)
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
    product_type: str = PRODUCT_WEEKLY,
    workbook_level: Optional[str] = None,
    rework_of_submission_id: Optional[int] = None,
    photos: Optional[list[UploadFile]] = File(default=None),
    photo: Optional[UploadFile] = File(default=None),
    db: Session = Depends(get_db),
):
    """관리자가 직접 학부모 사진을 업로드해서 제출 생성."""
    parent = db.query(Parent).filter(Parent.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="학부모를 찾을 수 없습니다")
    if product_type not in {PRODUCT_WEEKLY, PRODUCT_WORKBOOK}:
        raise HTTPException(status_code=400, detail="교재를 선택해주세요.")
    if product_type == PRODUCT_WEEKLY and not parent.weekly_words_enabled:
        raise HTTPException(status_code=400, detail="매주 3단어 이용 고객이 아닙니다.")
    purchase = None
    if product_type == PRODUCT_WORKBOOK:
        if workbook_level not in WORKBOOK_LEVELS:
            raise HTTPException(status_code=400, detail="8주 완성 교재단계를 선택해주세요.")
        purchase = (
            rework_purchase(db, parent_id, workbook_level, rework_of_submission_id, seoul_date())
            if rework_of_submission_id else
            active_purchase(db, parent_id, workbook_level=workbook_level)
        )
        if not purchase:
            raise HTTPException(status_code=409, detail="사용 가능한 8주 완성 첨삭권이 없습니다.")
    elif rework_of_submission_id:
        raise HTTPException(status_code=400, detail="매주 3단어에는 8주 완성 수정본을 연결할 수 없습니다.")

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
        product_type=product_type,
        workbook_level=purchase.workbook_level if purchase else None,
        rework_of_submission_id=rework_of_submission_id,
        photo_path=serialize_photo_paths(photo_paths),
        level=parent.level,
        status="pending",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    request_archive_check()
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
    if s.parent_id and s.product_type != PRODUCT_WORKBOOK:
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

    if s.product_type == PRODUCT_WORKBOOK:
        if s.workbook_level not in WORKBOOK_LEVELS:
            raise HTTPException(status_code=400, detail="8주 완성 교재단계가 없습니다.")
    else:
        validate_level(body.level)
        if body.stage is None or not (1 <= body.stage <= 10):
            raise HTTPException(status_code=400, detail="Stage must be between 1 and 10")

    previous_query = db.query(Submission).filter(
        Submission.parent_id == parent.id,
        Submission.product_type == (s.product_type or PRODUCT_WEEKLY),
        Submission.feedback_draft.isnot(None),
        Submission.id != submission_id,
    )
    if s.product_type == PRODUCT_WORKBOOK:
        previous_query = previous_query.filter(Submission.workbook_level == s.workbook_level)
    recent_submissions = previous_query.order_by(Submission.created_at.desc()).limit(3).all()
    previous_feedbacks = [rs.feedback_draft for rs in recent_submissions if rs.feedback_draft]

    try:
        feedback_text = sanitize_channel_feedback(
            generate_feedback(
                image_path=photo_paths,
                level_key=body.level,
                stage_num=body.stage,
                extra_instruction=body.extra_instruction or "",
                previous_feedbacks=previous_feedbacks,
                workbook_level=s.workbook_level if s.product_type == PRODUCT_WORKBOOK else None,
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
    if s.product_type != PRODUCT_WORKBOOK:
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
        "product_type": s.product_type,
    }


@router.delete("/submissions/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_submission(submission_id: int, db: Session = Depends(get_db)):
    """Delete a single submission and its uploaded photos."""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    if db.query(WorkbookUse).filter_by(submission_id=submission_id).first():
        raise HTTPException(status_code=409, detail="첨삭권 사용 이력이 있어 제출을 삭제할 수 없습니다.")

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
    if s.product_type == PRODUCT_WORKBOOK and s.rework_of_submission_id and not rework_purchase(
        db, s.parent_id, s.workbook_level, s.rework_of_submission_id, seoul_date(s.created_at)
    ):
        raise HTTPException(status_code=409, detail="연결된 수정본의 원본 첨삭을 확인할 수 없습니다.")
    if s.product_type == PRODUCT_WORKBOOK and not s.rework_of_submission_id:
        record_use(db, s)
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
            "weekly_words_enabled": p.weekly_words_enabled,
            "level": p.level,
            "levels": parent_levels_for_api(p),
            "created_at": to_utc_iso(p.created_at),
            "submission_count": len(p.submissions),
            "workbook_purchases": [purchase_balance(purchase) for purchase in p.workbook_purchases],
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
        existing.weekly_words_enabled = True
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


@router.post("/workbook-purchases/preview")
def preview_workbook_purchases(body: WorkbookImportRequest):
    rows, errors = parse_purchase_rows(body.text)
    return {"rows": rows, "errors": errors}


@router.post("/workbook-purchases/import")
def import_workbook_purchases(body: WorkbookImportRequest, db: Session = Depends(get_db)):
    result = import_purchase_rows(db, body.text)
    if result["errors"]:
        raise HTTPException(status_code=400, detail={"message": "입력한 행을 확인해주세요.", "errors": result["errors"]})
    return result


@router.get("/workbook-purchases")
def list_workbook_purchases(db: Session = Depends(get_db)):
    return [purchase_balance(p) for p in db.query(WorkbookPurchase).order_by(WorkbookPurchase.id.desc()).all()]


@router.get("/workbook-purchases/sheet-balances")
def workbook_sheet_balances(db: Session = Depends(get_db)):
    """Read-only balance feed for the existing onboarding/expiry Google Sheet."""
    rows = db.query(WorkbookPurchase, Parent.phone_number).join(
        Parent, Parent.id == WorkbookPurchase.parent_id
    ).all()
    return [{
        "purchase_id": purchase.id,
        "phone_number": phone,
        "workbook_level": purchase.workbook_level,
        "pass_type": purchase.pass_type,
        "purchase_date": purchase.purchase_date.isoformat(),
        "used_uses": purchase_used(purchase),
        "remaining_uses": purchase.total_uses - purchase_used(purchase),
    } for purchase, phone in rows]


@router.get("/storage/status")
def storage_status(db: Session = Depends(get_db)):
    """Volume usage breakdown for Railway /data."""
    result = get_storage_status(db)
    result["auto_archive"] = archive_status()
    return result


@router.post("/storage/archive-now", status_code=202)
def start_storage_archive_now():
    """Queue one verified R2 archive regardless of the normal size threshold."""
    run_id = request_archive_check(force=True)
    if not run_id:
        raise HTTPException(status_code=409, detail="R2 백업이 설정되지 않았거나 이미 실행 중입니다.")
    return {"run_id": run_id, "status": "started"}


@router.post("/storage/cleanup")
def storage_cleanup(body: StorageCleanupRequest, db: Session = Depends(get_db)):
    """
    Free disk space safely:
    - Remove worksheet photos for already-sent submissions (feedback text stays in DB)
    - Remove orphan files in uploads/
    - VACUUM SQLite database
    """
    return cleanup_storage(
        db,
        remove_sent_photos=body.remove_sent_photos,
        remove_orphans=body.remove_orphans,
        vacuum_database=body.vacuum_database,
    )


@router.get("/storage/backup/database")
def download_database_backup():
    """Download SQLite DB for offline backup."""
    db_path = database_file_path()
    if not db_path or not db_path.is_file():
        raise HTTPException(status_code=404, detail="SQLite database file not found.")

    return FileResponse(
        path=str(db_path),
        filename="yejinsaem-backup.db",
        media_type="application/octet-stream",
    )


@router.get("/storage/backup/photos")
def download_photos_backup(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Download all worksheet photos as a ZIP (back up before cleanup)."""
    try:
        zip_path, photo_count = create_photos_backup_zip(db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    background_tasks.add_task(lambda: zip_path.unlink(missing_ok=True))
    date_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return FileResponse(
        path=str(zip_path),
        filename=f"yejinsaem-photos-{date_label}.zip",
        media_type="application/zip",
        headers={"X-Photo-Count": str(photo_count)},
    )


@router.get("/parents/{parent_id}")
def get_parent(parent_id: int, db: Session = Depends(get_db)):
    """Get a single parent's details."""
    parent = db.query(Parent).filter(Parent.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")

    return serialize_parent(parent)


@router.get("/parents/{parent_id}/workbook-rework-options")
def get_workbook_rework_options(parent_id: int, db: Session = Depends(get_db)):
    today = seoul_date()
    rows = (
        db.query(Submission, WorkbookPurchase)
        .join(WorkbookUse, WorkbookUse.submission_id == Submission.id)
        .join(WorkbookPurchase, WorkbookPurchase.id == WorkbookUse.purchase_id)
        .filter(Submission.parent_id == parent_id,
                Submission.product_type == PRODUCT_WORKBOOK,
                Submission.status == "sent",
                WorkbookPurchase.expires_on >= today)
        .order_by(Submission.created_at.desc())
        .all()
    )
    return [{"submission_id": s.id, "workbook_level": s.workbook_level,
             "created_at": to_utc_iso(s.created_at)} for s, _ in rows]


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
    delete_submission_photo_files(submission)


@router.delete("/parents/{parent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_parent(parent_id: int, db: Session = Depends(get_db)):
    """Delete a parent and all associated submissions."""
    parent = db.query(Parent).filter(Parent.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    if parent.workbook_purchases:
        raise HTTPException(status_code=409, detail="8주 완성 구매·사용 내역이 있는 고객은 삭제할 수 없습니다.")

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
                "product_type": s.product_type,
                "workbook_level": s.workbook_level,
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
