import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parent_import import merge_parents_by_phone, parse_bulk_parent_rows


SAMPLE = """이지선\t010-8769-4830\t0\t5/26 구매자\t카톡\t패키지
김신예\t+1-857-998-2121\t8월 시작\t5/26 구매자\t카톡\t패키지
"""


def test_parse_bulk_parent_rows():
    rows, errors = parse_bulk_parent_rows(SAMPLE)
    assert len(errors) == 0
    assert len(rows) == 2
    assert rows[0]["child_name"] == "이지선"
    assert rows[0]["phone_number"] == "01087694830"
    assert rows[1]["phone_number"] == "18579982121"


def test_merge_package_levels():
    rows, _ = parse_bulk_parent_rows(SAMPLE)
    merged = merge_parents_by_phone(rows)
    package = next(p for p in merged if p["child_name"] == "이지선")
    assert package["levels"] == ["표현력", "초등기초", "초등심화"]
