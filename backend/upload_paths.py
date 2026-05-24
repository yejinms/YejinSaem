"""Resolve stored upload paths across local dev and Railway volume layouts."""

import os
from pathlib import Path

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
