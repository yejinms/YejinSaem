"""UTC datetime helpers for API serialization."""

from datetime import datetime, timezone


def utc_now_naive() -> datetime:
    """Naive UTC datetime for DB columns (compatible with existing rows)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_iso(dt: datetime | None) -> str | None:
    """Serialize DB datetime as ISO-8601 UTC with Z suffix for browsers."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")
