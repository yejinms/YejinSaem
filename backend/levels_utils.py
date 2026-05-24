"""
levels_utils.py - Parent level lists (표현력 / 초등기초 / 초등심화, multi-select).
"""

from __future__ import annotations

import json

LEVEL_ORDER = ["표현력", "초등기초", "초등심화"]
ALL_LEVELS = list(LEVEL_ORDER)

PRODUCT_TO_LEVELS: dict[str, list[str]] = {
    "표현력": ["표현력"],
    "기초": ["초등기초"],
    "심화": ["초등심화"],
    "패키지": ALL_LEVELS,
    "": ["표현력"],
}


def normalize_levels(raw: list[str] | None) -> list[str]:
    if not raw:
        raise ValueError("At least one level is required")
    seen: set[str] = set()
    result: list[str] = []
    for key in LEVEL_ORDER:
        if key in raw and key not in seen:
            seen.add(key)
            result.append(key)
    if not result:
        raise ValueError(f"Invalid levels: {raw}")
    return result


def resolve_levels_input(
    levels: list[str] | None,
    level: str | None,
    *,
    default: str = "표현력",
) -> list[str]:
    if levels:
        return normalize_levels(levels)
    if level:
        return normalize_levels([level])
    return normalize_levels([default])


def parse_parent_levels_json(levels_json: str | None, fallback_level: str | None) -> list[str]:
    if levels_json:
        try:
            data = json.loads(levels_json)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            strings = [item for item in data if isinstance(item, str)]
            if strings:
                return normalize_levels(strings)
    if fallback_level:
        return normalize_levels([fallback_level])
    return normalize_levels(["표현력"])


def dump_parent_levels(levels: list[str]) -> str:
    return json.dumps(normalize_levels(levels), ensure_ascii=False)


def apply_parent_levels(parent, levels: list[str]) -> None:
    normalized = normalize_levels(levels)
    parent.levels = dump_parent_levels(normalized)
    parent.level = normalized[0]


def parent_levels_for_api(parent) -> list[str]:
    return parse_parent_levels_json(getattr(parent, "levels", None), parent.level)


def products_to_levels(product: str) -> list[str]:
    key = (product or "").strip()
    return list(PRODUCT_TO_LEVELS.get(key, ["표현력"]))


def levels_from_sheet_rows(rows: list[dict]) -> list[str]:
    acc: list[str] = []
    for row in rows:
        acc.extend(products_to_levels(row.get("상품", "")))
    return normalize_levels(acc)
