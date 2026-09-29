"""Ask the onboarding Sheet to refresh after an 8-week feedback use is recorded."""

import logging
import os

import requests

logger = logging.getLogger(__name__)


def sync_workbook_sheet_now() -> bool:
    """Best effort: a failed push must not undo a feedback send or its DB use."""
    url = os.getenv("WORKBOOK_SHEET_PUSH_URL", "").strip()
    token = os.getenv("WORKBOOK_SHEET_SYNC_TOKEN", "").strip()
    if not url or not token:
        logger.warning("8-week Sheet push is not configured; scheduled sync will catch up")
        return False

    try:
        response = requests.post(url, json={"token": token}, timeout=15)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise ValueError("Sheet push did not return ok=true")
        return True
    except Exception as exc:
        logger.error("8-week Sheet push failed; scheduled sync will retry: %s", exc)
        return False
