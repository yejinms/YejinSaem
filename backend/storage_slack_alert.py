"""Send one Slack reminder when the private R2 backup bucket reaches 8 GB."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from upload_paths import upload_dir

logger = logging.getLogger(__name__)
WARNING_BYTES = 8_000_000_000


def _state_path() -> Path:
    return upload_dir().parent / ".r2-slack-alert.json"


def _webhook_url() -> str | None:
    url = os.getenv("SLACK_R2_WEBHOOK_URL", "").strip()
    if not url:
        return None
    if not url.startswith("https://hooks.slack.com/services/"):
        raise ValueError("SLACK_R2_WEBHOOK_URL must be a Slack incoming webhook URL")
    return url


def maybe_alert_r2_capacity(used_bytes: int) -> bool:
    """Post once above the warning limit; rearm after capacity falls below it."""
    url = _webhook_url()
    if not url:
        return False

    path = _state_path()
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        logger.exception("Could not read R2 Slack alert state")
        state = {}

    if used_bytes < WARNING_BYTES:
        if state.get("warning_sent_at"):
            path.unlink(missing_ok=True)
        return False
    if state.get("warning_sent_at"):
        return False

    used_gb = used_bytes / 1_000_000_000
    message = (
        f"⚠️ 예진쌤 첨삭 사진 백업 R2 사용량이 {used_gb:.2f}GB입니다 (알림 기준 8GB, 자동 백업 상한 9GB). "
        "Cloudflare R2의 yejinsaem-private-backup 버킷에서 오래된 사진 ZIP과 같은 시각의 DB 파일을 "
        "외장하드에 내려받아 확인한 다음 R2에서 삭제해 공간을 비워 주세요. "
        "확인: https://dash.cloudflare.com/"
    )
    response = requests.post(url, json={"text": message}, timeout=10)
    response.raise_for_status()
    if response.text.strip() != "ok":
        raise RuntimeError("Slack webhook did not confirm delivery")
    temp = path.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps({"warning_sent_at": datetime.now(timezone.utc).isoformat(),
                                    "used_bytes": used_bytes}), encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return True
