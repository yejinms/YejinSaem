"""
outbound_privacy.py - Keep parent/child names out of Kakao channel and friend-talk messages.
"""

from database import Parent


def internal_names_for_parent(parent: Parent | None) -> list[str]:
    if not parent:
        return []
    names = []
    if parent.child_name and parent.child_name.strip():
        names.append(parent.child_name.strip())
    return names


def strip_registered_names(text: str, names: list[str]) -> str:
    """Remove internal registration labels if they appear in outbound text."""
    if not text or not names:
        return text

    result = text
    for name in names:
        if len(name) < 2:
            continue
        result = result.replace(name, "우리 친구")
    return result


def sanitize_channel_feedback(text: str, parent: Parent | None) -> str:
    return strip_registered_names(text, internal_names_for_parent(parent))
