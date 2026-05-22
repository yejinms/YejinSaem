import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from levels_utils import levels_from_sheet_rows, products_to_levels


def test_package_maps_to_all_levels():
    assert products_to_levels("패키지") == ["표현력", "초등기초", "초등심화"]


def test_sheet_rows_union_levels():
    rows = [
        {"상품": "표현력"},
        {"상품": "기초"},
    ]
    assert levels_from_sheet_rows(rows) == ["표현력", "초등기초"]
