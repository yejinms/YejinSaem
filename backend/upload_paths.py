"""Resolve stored upload paths across local dev and Railway volume layouts."""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent


def upload_dir() -> Path:
    return Path(os.getenv("UPLOAD_DIR", "./uploads"))


def resolve_upload_file_path(stored_path: str) -> Path:
    """
    Find an uploaded image on disk.

    DB may store absolute paths from an older UPLOAD_DIR while the file still
    lives under the current upload directory (same basename).
    """
    raw = Path(stored_path.strip())
    candidates: list[Path] = []

    if raw.is_absolute():
        candidates.append(raw)

    candidates.extend([
        raw,
        BACKEND_DIR / stored_path,
        upload_dir() / raw.name,
        upload_dir() / stored_path,
    ])

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue

    raise FileNotFoundError(f"Image file not found: {stored_path}")


def get_submission_photo_paths(submission) -> list[str]:
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


def delete_submission_photo_files(submission) -> None:
    for stored_path in get_submission_photo_paths(submission):
        try:
            file_path = resolve_upload_file_path(stored_path)
            file_path.unlink()
        except FileNotFoundError:
            logger.warning("Upload file already missing: %s", stored_path)
        except OSError as exc:
            logger.warning("Failed to delete upload %s: %s", stored_path, exc)

