"""
parent_import.py - Parse spreadsheet paste and upsert parents.
"""

from __future__ import annotations

import re
from collections import defaultdict

from database import Parent
from levels_utils import levels_from_sheet_rows
from services.parent_match import pending_kakao_user_id
from levels_utils import apply_parent_levels
from validation import validate_child_age, validate_levels
from levels_utils import resolve_levels_input

from validation import normalize_phone_number


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped:
        return []
    if "\t" in stripped:
        return [part.strip() for part in stripped.split("\t")]
    return [part.strip() for part in re.split(r"\s{2,}", stripped)]


def normalize_phone_soft(value: str) -> tuple[str | None, str | None]:
    """Return (normalized_phone, error_message)."""
    try:
        return normalize_phone_number(value, required=True), None
    except Exception as exc:
        detail = getattr(exc, "detail", None)
        if isinstance(detail, str):
            return None, detail
        return None, str(exc)


def parse_bulk_parent_rows(text: str) -> tuple[list[dict], list[dict]]:
    """
    Parse tab/spreadsheet paste.

    Expected columns: 이름, 전화번호, (주차/메모), (태그), 채널, 상품
    """
    parsed: list[dict] = []
    errors: list[dict] = []

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = _split_row(line)
        if len(parts) < 2:
            errors.append({"line": line_no, "message": "열이 부족합니다 (이름, 전화번호 필요)"})
            continue

        name = parts[0].strip()
        phone_raw = parts[1].strip()
        if len(parts) >= 6:
            channel = parts[4].strip()
            product = parts[5].strip()
        elif len(parts) == 3:
            channel = ""
            product = parts[2].strip()
        else:
            channel = parts[-2].strip() if len(parts) >= 2 else ""
            product = parts[-1].strip()

        if not name:
            errors.append({"line": line_no, "message": "이름이 비어 있습니다"})
            continue

        phone, phone_err = normalize_phone_soft(phone_raw)
        if phone_err:
            errors.append({"line": line_no, "message": f"{phone_raw}: {phone_err}"})
            continue

        parsed.append(
            {
                "line": line_no,
                "child_name": name,
                "phone_number": phone,
                "channel": channel,
                "product": product,
            }
        )

    return parsed, errors


def merge_parents_by_phone(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["phone_number"]].append(row)

    merged: list[dict] = []
    for phone, phone_rows in grouped.items():
        levels = levels_from_sheet_rows([{"상품": r["product"]} for r in phone_rows])
        name_row = phone_rows[0]
        for candidate in phone_rows:
            if len(candidate["child_name"]) > len(name_row["child_name"]):
                name_row = candidate
        merged.append(
            {
                "phone_number": phone,
                "child_name": name_row["child_name"],
                "levels": levels,
                "level": levels[0],
                "channels": sorted({r["channel"] for r in phone_rows if r.get("channel")}),
                "source_lines": [r["line"] for r in phone_rows],
            }
        )
    merged.sort(key=lambda item: item["child_name"])
    return merged


def filter_by_channel(parents: list[dict], channel: str | None) -> list[dict]:
    if not channel:
        return parents
    target = channel.strip()
    return [p for p in parents if target in (p.get("channels") or [])]


def upsert_parent(
    db,
    *,
    phone_number: str,
    child_name: str,
    levels: list[str],
    child_age: int | None = None,
    kakao_user_id: str | None = None,
) -> tuple[Parent, bool]:
    resolved_levels = validate_levels(resolve_levels_input(levels, None))
    if child_age is not None:
        validate_child_age(child_age)

    manual_kakao = (kakao_user_id or "").strip()
    existing = db.query(Parent).filter(Parent.phone_number == phone_number).first()

    if existing:
        existing.child_name = child_name
        existing.child_age = child_age
        existing.phone_number = phone_number
        apply_parent_levels(existing, resolved_levels)
        if manual_kakao:
            existing.kakao_user_id = manual_kakao
        db.commit()
        db.refresh(existing)
        return existing, False

    parent = Parent(
        kakao_user_id=manual_kakao or pending_kakao_user_id(phone_number),
        phone_number=phone_number,
        child_name=child_name,
        child_age=child_age,
        level=resolved_levels[0],
    )
    apply_parent_levels(parent, resolved_levels)
    db.add(parent)
    db.commit()
    db.refresh(parent)
    return parent, True


def import_parents_from_text(
    db,
    text: str,
    *,
    channel_filter: str | None = None,
) -> dict:
    rows, parse_errors = parse_bulk_parent_rows(text)
    merged = merge_parents_by_phone(rows)
    if channel_filter:
        merged = filter_by_channel(merged, channel_filter)

    created = updated = failed = 0
    results: list[dict] = []

    for parent in merged:
        try:
            _, is_created = upsert_parent(
                db,
                phone_number=parent["phone_number"],
                child_name=parent["child_name"],
                levels=parent["levels"],
            )
            if is_created:
                created += 1
            else:
                updated += 1
            results.append(
                {
                    "phone_number": parent["phone_number"],
                    "child_name": parent["child_name"],
                    "levels": parent["levels"],
                    "created": is_created,
                }
            )
        except Exception as exc:
            failed += 1
            detail = getattr(exc, "detail", str(exc))
            parse_errors.append(
                {
                    "line": parent.get("source_lines", [None])[0],
                    "message": f"{parent['child_name']} ({parent['phone_number']}): {detail}",
                }
            )

    return {
        "created": created,
        "updated": updated,
        "failed": failed,
        "parsed_rows": len(rows),
        "imported": len(merged),
        "errors": parse_errors,
        "results": results,
    }
