#!/usr/bin/env python3
"""Import parents from TSV paste file into local SQLite DB."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal, init_db
from parent_import import import_parents_from_text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "tsv",
        type=Path,
        nargs="?",
        default=Path(__file__).resolve().parents[1] / "data" / "bulk_parents_20260526.tsv",
    )
    parser.add_argument("--channel", default=None, help='Only import rows with this channel (e.g. "카톡")')
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    text = args.tsv.read_text(encoding="utf-8")
    if args.dry_run:
        from parent_import import merge_parents_by_phone, parse_bulk_parent_rows

        rows, errors = parse_bulk_parent_rows(text)
        merged = merge_parents_by_phone(rows)
        print(f"rows={len(rows)} parents={len(merged)} errors={len(errors)}")
        for parent in merged:
            print(parent["child_name"], parent["phone_number"], parent["levels"])
        return 0

    init_db()
    db = SessionLocal()
    try:
        result = import_parents_from_text(db, text, channel_filter=args.channel)
    finally:
        db.close()

    print(
        f"created={result['created']} updated={result['updated']} "
        f"failed={result['failed']} imported={result['imported']}"
    )
    if result["errors"]:
        for err in result["errors"]:
            print("error:", err)
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
