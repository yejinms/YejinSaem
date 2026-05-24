#!/usr/bin/env python3
"""
Import parents from Google Sheets CSV export (수신자 리스트).

- 채널=카톡만 포함
- 같은 전화번호의 여러 상품 행 → 레벨 합집합
- 패키지 → 표현력 + 초등기초 + 초등심화

Example:
  cd backend
  python scripts/import_parents_from_csv.py \\
    --csv "/path/to/수신자 리스트.csv" \\
    --channel 카톡 \\
    --api-base https://yejinsaem-production.up.railway.app
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

try:
    import httpx
except ImportError:
    print("httpx required: pip install httpx", file=sys.stderr)
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from levels_utils import levels_from_sheet_rows  # noqa: E402


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def normalize_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("010"):
        return digits
    return None


def clean_name(value: str) -> str:
    name = re.sub(r"\([^)]*\)", "", value or "").strip()
    return name or (value or "").strip()


def pick_name_row(rows: list[dict]) -> dict:
    """Prefer the row with the highest numeric send week for display name."""
    best = rows[0]
    best_week = -1
    for row in rows:
        text = (row.get("마지막 발송 주차(첫가입시 0)") or "").strip()
        if text == "발송 완료":
            week = 0
        else:
            try:
                week = int(text)
            except ValueError:
                week = 0
        if week >= best_week:
            best_week = week
            best = row
    return best


def load_kakao_parents(csv_path: Path, channel: str) -> list[dict]:
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if (row.get("채널") or "").strip() != channel:
            continue
        phone = normalize_phone(row.get("수신 연락처", ""))
        if not phone:
            continue
        grouped[phone].append(row)

    parents = []
    for phone, phone_rows in grouped.items():
        name_row = pick_name_row(phone_rows)
        levels = levels_from_sheet_rows(phone_rows)
        parents.append(
            {
                "phone_number": phone,
                "child_name": clean_name(name_row.get("구매자 ID", "")),
                "levels": levels,
                "level": levels[0],
            }
        )
    parents.sort(key=lambda p: p["child_name"])
    return parents


def import_parents(api_base: str, parents: list[dict], admin_password: str) -> tuple[int, int, int]:
    headers = {}
    if admin_password:
        headers["Authorization"] = f"Bearer {quote(admin_password, safe='')}"

    created = updated = failed = 0
    with httpx.Client(base_url=api_base.rstrip("/"), timeout=60.0) as client:
        for parent in parents:
            try:
                res = client.post("/admin/parents", json=parent, headers=headers)
                res.raise_for_status()
                body = res.json()
                if body.get("created"):
                    created += 1
                else:
                    updated += 1
            except Exception as e:
                failed += 1
                print(f"FAIL {parent['phone_number']} {parent['child_name']}: {e}", file=sys.stderr)
    return created, updated, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="Import parents from CSV into YejinSaem admin API")
    parser.add_argument("--csv", required=True, type=Path, help="Path to exported CSV")
    parser.add_argument("--channel", default="카톡", help='Filter by channel column (default: "카톡")')
    parser.add_argument(
        "--api-base",
        default=os.getenv("IMPORT_API_BASE", "http://127.0.0.1:8000"),
        help="API base URL (default: IMPORT_API_BASE or localhost)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse only, do not POST")
    args = parser.parse_args()

    backend_dir = Path(__file__).resolve().parents[1]
    load_dotenv(backend_dir / ".env")

    if not args.csv.is_file():
        print(f"CSV not found: {args.csv}", file=sys.stderr)
        return 1

    parents = load_kakao_parents(args.csv, args.channel)
    multi = [p for p in parents if len(p["levels"]) > 1]
    print(f"channel={args.channel!r} -> {len(parents)} unique parents ({len(multi)} with 2+ levels)")

    if args.dry_run:
        for p in parents[:8]:
            print(" ", p)
        if len(parents) > 8:
            print(f"  ... and {len(parents) - 8} more")
        return 0

    admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
    if not admin_password:
        print("ADMIN_PASSWORD is not set (backend/.env or env)", file=sys.stderr)
        return 1

    created, updated, failed = import_parents(args.api_base, parents, admin_password)
    print(f"done: created={created} updated={updated} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
