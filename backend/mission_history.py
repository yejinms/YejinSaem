"""
mission_history.py - Last selected mission for a child (from prior feedback generation)
"""

from datetime_utils import to_utc_iso
from prompts import LEVELS


def _stage_info(level_key: str, stage_num: int) -> dict:
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


def get_last_selected_mission(db, parent_id: int, exclude_submission_id: int) -> dict | None:
    """Most recent submission where admin chose level+stage for feedback generation."""
    from database import Submission

    prior = (
        db.query(Submission)
        .filter(
            Submission.parent_id == parent_id,
            Submission.id != exclude_submission_id,
            Submission.level.isnot(None),
            Submission.stage.isnot(None),
        )
        .order_by(Submission.updated_at.desc())
        .first()
    )
    if not prior:
        return None

    stage_info = _stage_info(prior.level, prior.stage)
    return {
        "submission_id": prior.id,
        "level": prior.level,
        "stage": prior.stage,
        "stage_title": stage_info.get("stage_title"),
        "stage_mission": stage_info.get("stage_mission"),
        "updated_at": to_utc_iso(prior.updated_at),
    }

