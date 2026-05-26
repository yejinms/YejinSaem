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


def build_mission_review_instruction(mission: dict) -> str:
    title = mission.get("stage_title") or ""
    mission_expr = mission.get("stage_mission") or ""
    return (
        "[지난 미션 검토] 지난번 피드백 생성 시 선택한 미션은 "
        f"{mission['level']} {mission['stage']}단계 「{title}」입니다. "
        f"기대 표현: {mission_expr}. "
        "오늘 사진 속 글에서 위 미션을 잘 수행했는지 먼저 확인하고, "
        "잘 했다면 피드백 앞부분에서 구체적으로 칭찬한 뒤, 이번 주 미션 달성 피드백을 이어 주세요. "
        "잘 보이지 않으면 억지로 칭찬하지 마세요."
    )
