"""Archive photos and SQLite to private R2 before removing archived sent photos."""

from __future__ import annotations

import logging
import os
import hashlib
import json
import sqlite3
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config

from database import SessionLocal, Submission
from storage_maintenance import create_photos_backup_snapshot, get_storage_status
from upload_paths import get_submission_photo_paths, resolve_upload_file_path, upload_dir

logger = logging.getLogger(__name__)
THRESHOLD_BYTES = 350_000_000
R2_ARCHIVE_MAX_BYTES = 9_000_000_000
R2_WARNING_BYTES = 8_000_000_000
_worker_lock = threading.Lock()


def _state_path() -> Path:
    return upload_dir().parent / ".r2-archive-status.json"


def _save_state(state: dict) -> None:
    path = _state_path()
    temp = path.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)
    except OSError:
        logger.exception("Could not save R2 archive status")
        temp.unlink(missing_ok=True)


def configured() -> bool:
    return (
        os.getenv("AUTO_ARCHIVE_ENABLED", "false").lower() == "true"
        and all(os.getenv(name) for name in (
            "R2_ACCOUNT_ID", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
        ))
    )


def request_archive_check() -> None:
    """Called after startup and committed image uploads; never blocks a customer request."""
    if not configured() or not _worker_lock.acquire(blocking=False):
        return
    threading.Thread(target=_run_worker, name="storage-auto-archive", daemon=True).start()


def _run_worker() -> None:
    try:
        with SessionLocal() as db:
            result = archive_if_needed(db)
            if result:
                logger.info("R2 archive completed: %s", result)
                _save_state({"last_success_at": datetime.now(timezone.utc).isoformat(),
                             "photos_key": result["photos_key"],
                             "database_key": result["database_key"],
                             "last_error": None})
    except Exception:
        logger.exception("R2 archive failed; source photos were retained unless individually verified")
        _save_state({"last_error_at": datetime.now(timezone.utc).isoformat(),
                     "last_error": "R2 백업이 실패했습니다. Railway 로그를 확인하세요."})
    finally:
        _worker_lock.release()


def _r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(connect_timeout=15, read_timeout=120, retries={"max_attempts": 3}),
    )


def r2_used_bytes(client) -> int:
    total = 0
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=os.environ["R2_BUCKET"]):
        total += sum(item["Size"] for item in page.get("Contents", []))
    return total


def archive_status() -> dict:
    result = {
        "enabled": configured(),
        "threshold_bytes": THRESHOLD_BYTES,
        "warning_bytes": R2_WARNING_BYTES,
        "max_bytes": R2_ARCHIVE_MAX_BYTES,
    }
    try:
        if _state_path().is_file():
            result.update(json.loads(_state_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        logger.exception("Could not read R2 archive status")
    if configured():
        try:
            result["used_bytes"] = r2_used_bytes(_r2_client())
        except Exception:
            logger.exception("Could not read R2 archive usage")
            result["usage_error"] = True
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_database_snapshot(db) -> Path:
    bind = db.get_bind()
    source = Path(bind.url.database) if bind.url.get_backend_name() == "sqlite" and bind.url.database else None
    if not source or not source.is_file():
        raise RuntimeError("SQLite DB가 없어 전체 첨삭 기록을 백업할 수 없습니다.")
    fd, name = tempfile.mkstemp(prefix="yejinsaem-db-", suffix=".sqlite3")
    os.close(fd)
    target = Path(name)
    try:
        with sqlite3.connect(str(source)) as original, sqlite3.connect(str(target)) as copy:
            original.backup(copy)
            if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("DB 백업 무결성 검사에 실패했습니다.")
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def upload_verified(client, local_path: Path, key: str) -> None:
    """Read the object back in chunks; deletion requires matching remote bytes."""
    bucket = os.environ["R2_BUCKET"]
    size = local_path.stat().st_size
    digest = _sha256(local_path)
    client.upload_file(
        str(local_path), bucket, key,
        ExtraArgs={"ContentType": "application/zip" if key.endswith(".zip") else "application/octet-stream",
                   "Metadata": {"sha256": digest}},
    )
    head = client.head_object(Bucket=bucket, Key=key)
    if head["ContentLength"] != size or head.get("Metadata", {}).get("sha256") != digest:
        raise RuntimeError("R2 업로드 크기 또는 체크섬 메타데이터가 일치하지 않습니다.")
    remote = client.get_object(Bucket=bucket, Key=key)["Body"]
    remote_digest = hashlib.sha256()
    remote_size = 0
    try:
        for chunk in remote.iter_chunks(chunk_size=1024 * 1024):
            if chunk:
                remote_digest.update(chunk)
                remote_size += len(chunk)
    finally:
        remote.close()
    if remote_size != size or remote_digest.hexdigest() != digest:
        raise RuntimeError("R2에서 다시 받은 파일이 원본과 일치하지 않습니다.")


def cleanup_archived_sent_photos(db, entries: list[dict]) -> int:
    """Delete only files in the verified ZIP that still belong to sent submissions."""
    by_submission: dict[int, list[dict]] = {}
    for entry in entries:
        if entry["status"] == "sent" and entry["submission_id"] is not None:
            by_submission.setdefault(entry["submission_id"], []).append(entry)

    # Shared paths are rare, but never remove a photo another active submission needs.
    active_paths = set()
    for submission in db.query(Submission).filter(Submission.status != "sent").all():
        for stored_path in get_submission_photo_paths(submission):
            try:
                active_paths.add(resolve_upload_file_path(stored_path))
            except FileNotFoundError:
                pass

    removed = 0
    for submission_id, archived in by_submission.items():
        submission = db.query(Submission).filter(Submission.id == submission_id).first()
        if not submission or submission.status != "sent":
            continue
        if submission.photo_path != archived[0]["stored_photo_path"]:
            continue
        stored_paths = get_submission_photo_paths(submission)
        if len(stored_paths) != len(archived):
            continue  # Missing photos were not in the ZIP.
        files = []
        for stored_path in stored_paths:
            try:
                files.append(resolve_upload_file_path(stored_path))
            except FileNotFoundError:
                break
        if len(files) != len(archived) or any(path in active_paths for path in files):
            continue
        archived_by_path = {entry["path"]: entry for entry in archived}
        if any(
            (entry := archived_by_path.get(path)) is None
            or path.stat().st_size != entry["bytes"]
            or path.stat().st_mtime_ns != entry["mtime_ns"]
            for path in files
        ):
            continue
        submission.photo_path = None
        db.commit()
        for path in files:
            try:
                path.unlink()
                removed += 1
            except OSError:
                logger.exception("Could not delete archived photo %s; it remains an orphan", path)
    return removed


def archive_if_needed(db) -> dict | None:
    if not configured():
        return None
    status = get_storage_status(db)
    if status["total_bytes"] < THRESHOLD_BYTES:
        return None
    if status["sent_submissions_with_photos"] == 0:
        logger.warning("Volume crossed archive threshold, but no sent photos can be cleaned")
        return None

    zip_path, count, entries = create_photos_backup_snapshot(db)
    db_path = None
    try:
        if not any(entry["status"] == "sent" for entry in entries):
            logger.warning("Volume crossed archive threshold, but no sent files exist in the ZIP")
            return None
        db_path = create_database_snapshot(db)
        client = _r2_client()
        used = r2_used_bytes(client)
        added = zip_path.stat().st_size + db_path.stat().st_size
        if used + added > R2_ARCHIVE_MAX_BYTES:
            raise RuntimeError("R2 보관 상한 9GB에 가까워져 백업을 중단했습니다. 외장하드로 옮긴 뒤 다시 시도하세요.")
        prefix = datetime.now(timezone.utc).strftime("backups/%Y/%m/%Y-%m-%dT%H-%M-%SZ")
        prefix += f"-{uuid.uuid4().hex[:8]}"
        photos_key = f"{prefix}-photos.zip"
        database_key = f"{prefix}-database.sqlite3"
        try:
            upload_verified(client, zip_path, photos_key)
            upload_verified(client, db_path, database_key)
        except Exception:
            # This run has not touched source photos. Remove its incomplete remote pair.
            for key in (photos_key, database_key):
                try:
                    client.delete_object(Bucket=os.environ["R2_BUCKET"], Key=key)
                except Exception:
                    logger.exception("Could not remove incomplete R2 object %s", key)
            raise
        removed = cleanup_archived_sent_photos(db, entries)
        return {"photos_key": photos_key, "database_key": database_key,
                "photos_archived": count, "sent_photos_removed": removed,
                "r2_used_bytes_after": used + added}
    finally:
        zip_path.unlink(missing_ok=True)
        if db_path:
            db_path.unlink(missing_ok=True)
