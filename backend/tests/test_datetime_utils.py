from datetime import datetime, timezone

from datetime_utils import to_utc_iso, utc_now_naive


def test_to_utc_iso_naive_appends_z():
    assert to_utc_iso(datetime(2026, 5, 23, 1, 0, 0)) == "2026-05-23T01:00:00Z"


def test_to_utc_iso_aware_converts_to_utc():
    aware = datetime(2026, 5, 23, 10, 0, 0, tzinfo=timezone.utc)
    assert to_utc_iso(aware) == "2026-05-23T10:00:00Z"


def test_utc_now_naive_has_no_tzinfo():
    value = utc_now_naive()
    assert value.tzinfo is None
