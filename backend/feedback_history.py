"""
feedback_history.py - Build prior feedback context for Claude prompts
"""

from datetime_utils import to_utc_iso
from prompts import LEVELS


def _stage_info(level_key: str | None, stage_num: int | None) -> dict:
    if not level_key or not stage_num:
        return {}
    level = LEVELS.get(level_key)
    if not level:
        return {}
    stage = level["stages"].get(stage_num)
    if not stage:
        return {}
    return {
        "stage_title": stage["title"],
        "stage_mission": stage["mission"],
    }


def build_previous_feedback_contexts(submissions: list) -> list[dict]:
    """Turn past submissions into prompt-safe history (no child/parent names)."""

    def priority(submission) -> tuple:
        status_rank = {
            "sent": 0,
            "approved": 1,
            "generated": 2,
        }.get(submission.status, 3)
        created = submission.created_at.timestamp() if submission.created_at else 0
        return (status_rank, -created)

    ordered = sorted(submissions, key=priority)[:5]
    contexts = []
    for submission in ordered:
        if not submission.feedback_draft:
            continue
        stage_info = _stage_info(submission.level, submission.stage)
        contexts.append(
            {
                "created_at": to_utc_iso(submission.created_at),
                "status": submission.status,
                "level": submission.level,
                "stage": submission.stage,
                "stage_title": stage_info.get("stage_title"),
                "stage_mission": stage_info.get("stage_mission"),
                "feedback_excerpt": submission.feedback_draft[:500],
            }
        )
    return contexts
