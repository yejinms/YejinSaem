"""
storage_maintenance.py - Railway volume usage stats and safe cleanup.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from database import Submission
from datetime_utils import to_utc_iso
from upload_paths import get_submission_photo_paths, resolve_upload_file_path, upload_dir

logger = logging.getLogger(__name__)


def database_file_path() -> Path | None:
    url = os.getenv("DATABASE_URL", "sqlite:///./yejinsaem.db")
    if not url.startswith("sqlite"):
        return None
    raw = url.removeprefix("sqlite:///")
    return Path(raw)


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    if path.is_file():
        return path.stat().st_size
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                continue
    return total


def _format_bytes(num: int) -> str:
    if num < 1024:
        return f"{num} B"
    if num < 1024 * 1024:
        return f"{num / 1024:.1f} KB"
    if num < 1024 * 1024 * 1024:
        return f"{num / (1024 * 1024):.1f} MB"
    return f"{num / (1024 * 1024 * 1024):.2f} GB"


def referenced_upload_files(db) -> set[str]:
    refs: set[str] = set()
    submissions = db.query(Submission).all()
    for submission in submissions:
        for stored_path in get_submission_photo_paths(submission):
            try:
                refs.add(str(resolve_upload_file_path(stored_path).resolve()))
            except FileNotFoundError:
                refs.add(stored_path)
    return refs


def get_storage_status(db) -> dict:
    uploads_path = upload_dir()
    db_path = database_file_path()

    upload_bytes = _dir_size(uploads_path)
    db_bytes = db_path.stat().st_size if db_path and db_path.is_file() else 0

    refs = referenced_upload_files(db)
    orphan_files: list[dict] = []
    orphan_bytes = 0
    if uploads_path.exists():
        for file_path in uploads_path.rglob("*"):
            if not file_path.is_file():
                continue
            resolved = str(file_path.resolve())
            if resolved not in refs:
                size = file_path.stat().st_size
                orphan_files.append({"path": file_path.name, "bytes": size})
                orphan_bytes += size

    sent_with_photos = (
        db.query(Submission)
        .filter(Submission.status == "sent", Submission.photo_path.isnot(None))
        .count()
    )
    pending_with_photos = (
        db.query(Submission)
        .filter(Submission.status != "sent", Submission.photo_path.isnot(None))
        .count()
    )

    total_bytes = upload_bytes + db_bytes
    return {
        "upload_dir": str(uploads_path),
        "database_path": str(db_path) if db_path else None,
        "upload_bytes": upload_bytes,
        "upload_human": _format_bytes(upload_bytes),
        "database_bytes": db_bytes,
        "database_human": _format_bytes(db_bytes),
        "total_bytes": total_bytes,
        "total_human": _format_bytes(total_bytes),
        "upload_file_count": sum(1 for _ in uploads_path.rglob("*") if _.is_file()) if uploads_path.exists() else 0,
        "orphan_file_count": len(orphan_files),
        "orphan_bytes": orphan_bytes,
        "orphan_human": _format_bytes(orphan_bytes),
        "sent_submissions_with_photos": sent_with_photos,
        "active_submissions_with_photos": pending_with_photos,
        "backup_hint": (
            "용량 확보 순서: ① 사진 ZIP 백업 다운로드 → ② 용량 정리. "
            "DB 백업은 학부모·피드백용(용량은 작음)."
        ),
    }


def create_photos_backup_zip(db) -> tuple[Path, int]:
    """Pack all upload photos into a zip on /tmp (not on the volume)."""
    uploads_path = upload_dir()
    if not uploads_path.exists():
        raise ValueError("업로드 폴더가 없습니다.")

    entries: list[dict] = []
    seen_files: set[str] = set()

    submissions = (
        db.query(Submission)
        .filter(Submission.photo_path.isnot(None))
        .order_by(Submission.id.asc())
        .all()
    )
    for submission in submissions:
        parent_name = submission.parent.child_name if submission.parent else "미등록"
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in parent_name)[:40]
        for index, stored_path in enumerate(get_submission_photo_paths(submission), start=1):
            try:
                file_path = resolve_upload_file_path(stored_path)
            except FileNotFoundError:
                continue
            resolved = str(file_path.resolve())
            if resolved in seen_files:
                continue
            seen_files.add(resolved)
            arcname = (
                f"photos/submission-{submission.id}_{safe_name}/"
                f"photo-{index}{file_path.suffix.lower() or '.jpg'}"
            )
            entries.append(
                {
                    "arcname": arcname,
                    "path": file_path,
                    "submission_id": submission.id,
                    "child_name": parent_name,
                    "status": submission.status,
                    "created_at": to_utc_iso(submission.created_at),
                    "bytes": file_path.stat().st_size,
                }
            )

    for file_path in uploads_path.rglob("*"):
        if not file_path.is_file():
            continue
        resolved = str(file_path.resolve())
        if resolved in seen_files:
            continue
        seen_files.add(resolved)
        entries.append(
            {
                "arcname": f"photos/orphan/{file_path.name}",
                "path": file_path,
                "submission_id": None,
                "child_name": None,
                "status": "orphan",
                "created_at": None,
                "bytes": file_path.stat().st_size,
            }
        )

    if not entries:
        raise ValueError("백업할 사진이 없습니다.")

    fd, tmp_name = tempfile.mkstemp(suffix=".zip", prefix="yejinsaem-photos-")
    os.close(fd)
    zip_path = Path(tmp_name)

    manifest = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for entry in entries:
            archive.write(entry["path"], arcname=entry["arcname"])
            manifest.append(
                {
                    "path": entry["arcname"],
                    "submission_id": entry["submission_id"],
                    "child_name": entry["child_name"],
                    "status": entry["status"],
                    "created_at": entry["created_at"],
                    "bytes": entry["bytes"],
                }
            )
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "photo_count": len(entries),
                    "files": manifest,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    return zip_path, len(entries)


def cleanup_storage(
    db,
    *,
    remove_sent_photos: bool = True,
    remove_orphans: bool = True,
    vacuum_database: bool = True,
) -> dict:
    freed_bytes = 0
    removed_sent = 0
    removed_orphans = 0

    if remove_sent_photos:
        sent_submissions = (
            db.query(Submission)
            .filter(Submission.status == "sent", Submission.photo_path.isnot(None))
            .all()
        )
        for submission in sent_submissions:
            for stored_path in get_submission_photo_paths(submission):
                try:
                    file_path = resolve_upload_file_path(stored_path)
                    size = file_path.stat().st_size
                    file_path.unlink()
                    freed_bytes += size
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    logger.warning("Failed to delete sent photo %s: %s", stored_path, exc)
            submission.photo_path = None
            removed_sent += 1
        if removed_sent:
            db.commit()

    if remove_orphans:
        refs = referenced_upload_files(db)
        uploads_path = upload_dir()
        if uploads_path.exists():
            for file_path in uploads_path.rglob("*"):
                if not file_path.is_file():
                    continue
                if str(file_path.resolve()) in refs:
                    continue
                try:
                    size = file_path.stat().st_size
                    file_path.unlink()
                    freed_bytes += size
                    removed_orphans += 1
                except OSError as exc:
                    logger.warning("Failed to delete orphan %s: %s", file_path, exc)

    vacuumed = False
    if vacuum_database:
        db_path = database_file_path()
        if db_path and db_path.is_file():
            before = db_path.stat().st_size
            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute("VACUUM")
                conn.commit()
            finally:
                conn.close()
            after = db_path.stat().st_size
            if after < before:
                freed_bytes += before - after
            vacuumed = True

    status = get_storage_status(db)
    return {
        "freed_bytes": freed_bytes,
        "freed_human": _format_bytes(freed_bytes),
        "removed_sent_submission_photos": removed_sent,
        "removed_orphan_files": removed_orphans,
        "vacuumed_database": vacuumed,
        "storage": status,
    }
