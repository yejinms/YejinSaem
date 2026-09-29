from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import workbook_sheet_sync


def test_push_uses_existing_sync_token_and_waits_for_success(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    monkeypatch.setenv("WORKBOOK_SHEET_PUSH_URL", "https://example.com/exec")
    monkeypatch.setenv("WORKBOOK_SHEET_SYNC_TOKEN", "test-token")
    monkeypatch.setattr(workbook_sheet_sync.requests, "post",
                        lambda url, json, timeout: calls.append((url, json, timeout)) or Response())

    assert workbook_sheet_sync.sync_workbook_sheet_now() is True
    assert calls == [("https://example.com/exec", {"token": "test-token"}, 15)]


def test_push_failure_does_not_raise_or_claim_success(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": False, "error": "sync_failed"}

    monkeypatch.setenv("WORKBOOK_SHEET_PUSH_URL", "https://example.com/exec")
    monkeypatch.setenv("WORKBOOK_SHEET_SYNC_TOKEN", "test-token")
    monkeypatch.setattr(workbook_sheet_sync.requests, "post",
                        lambda url, json, timeout: Response())

    assert workbook_sheet_sync.sync_workbook_sheet_now() is False
