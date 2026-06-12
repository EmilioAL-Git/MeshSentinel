from datetime import datetime, timedelta, timezone

from noc.application.dashboard import is_stale


def test_stale_when_no_heartbeat():
    assert is_stale(None, 90)


def test_fresh_heartbeat_is_not_stale():
    assert not is_stale(datetime.now(timezone.utc) - timedelta(seconds=30), 90)


def test_old_heartbeat_is_stale():
    assert is_stale(datetime.now(timezone.utc) - timedelta(seconds=120), 90)


def test_naive_datetime_is_interpreted_as_utc():
    naive_recent = datetime.now(timezone.utc).replace(tzinfo=None)
    assert not is_stale(naive_recent, 90)
