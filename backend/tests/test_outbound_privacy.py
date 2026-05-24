import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.outbound_privacy import sanitize_channel_feedback, strip_registered_names


class _Parent:
    child_name = "서연"


def test_strip_registered_names():
    text = "서연이 오늘 글을 잘 썼어요."
    assert "서연" not in strip_registered_names(text, ["서연"])
    assert "우리 친구" in strip_registered_names(text, ["서연"])


def test_sanitize_channel_feedback():
    parent = _Parent()
    assert "서연" not in sanitize_channel_feedback("서연 학부모님께 전달합니다.", parent)
