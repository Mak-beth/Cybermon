"""R11-B tests — stateful failed-login detection via DB window query.

Each test seeds a temporary SQLite database with init_db + insert_events,
then calls detect_failed_logins_from_db directly.  The function counts DB
rows in the window (the caller is expected to have inserted the current
batch already, as the ingest endpoint does), and fires at count >= threshold.
"""
from datetime import datetime, timedelta

from src.detection.rules.failed_logins import detect_failed_logins_from_db
from src.storage.db import init_db
from src.storage.writer import insert_events, insert_violation


def _cfg(threshold: int = 2, window_minutes: int = 10) -> dict:
    return {"detection": {"failed_logins": {
        "threshold": threshold,
        "time_window_minutes": window_minutes,
    }}}


def _evt(username: str, ts: datetime, host: str = "host-1",
         ip: str = "10.0.0.1", status: str = "FAILED") -> dict:
    return {
        "timestamp": ts,
        "username": username,
        "source_ip": ip,
        "resource": None,
        "action": "ssh_login",
        "status_code": status,
        "source_host": host,
    }


def _make_db(tmp_path, events: list[dict]) -> str:
    db_path = str(tmp_path / "r11b.db")
    init_db(db_path)
    if events:
        insert_events(events, db_path)
    return db_path


def test_single_event_below_threshold_no_violation(tmp_path):
    """One FAILED event total (the batch event, already in DB); threshold=2."""
    now = datetime.now()
    batch = [_evt("alice", now)]
    db_path = _make_db(tmp_path, batch)

    result = detect_failed_logins_from_db(batch, _cfg(threshold=2), db_path, "host-1")
    assert result == []


def test_db_plus_batch_crosses_threshold(tmp_path):
    """One older FAILED event in DB + one batch event = 2; threshold=2 fires.

    Also verified at threshold=5 with four prior events + one batch event,
    per the acceptance criterion that both threshold configs work.
    """
    now = datetime.now()
    older = _evt("alice", now - timedelta(minutes=3))
    batch = [_evt("alice", now)]
    db_path = _make_db(tmp_path, [older] + batch)

    result = detect_failed_logins_from_db(batch, _cfg(threshold=2), db_path, "host-1")
    assert len(result) == 1
    assert result[0]["violation_type"] == "failed_logins"
    assert result[0]["username"] == "alice"
    assert "2 failed logins" in result[0]["detail"]

    # threshold=5: four prior + one batch = 5 → fires
    prior = [_evt("bob", now - timedelta(minutes=i + 1)) for i in range(4)]
    batch5 = [_evt("bob", now)]
    db_path5 = _make_db(tmp_path / "t5", prior + batch5)
    result5 = detect_failed_logins_from_db(batch5, _cfg(threshold=5), db_path5, "host-1")
    assert len(result5) == 1
    assert result5[0]["username"] == "bob"


def test_spread_across_three_batches(tmp_path):
    """Slow brute force: two events from earlier batches + one arriving; threshold=3."""
    now = datetime.now()
    earlier = [
        _evt("root", now - timedelta(minutes=6)),
        _evt("root", now - timedelta(minutes=4)),
    ]
    batch = [_evt("root", now)]
    db_path = _make_db(tmp_path, earlier + batch)

    result = detect_failed_logins_from_db(batch, _cfg(threshold=3), db_path, "host-1")
    assert len(result) == 1
    assert result[0]["username"] == "root"
    assert "3 failed logins" in result[0]["detail"]


def test_old_db_event_outside_window_ignored(tmp_path):
    """A DB event older than the window does not count toward the threshold."""
    now = datetime.now()
    stale = _evt("alice", now - timedelta(minutes=45))   # outside 10-min window
    batch = [_evt("alice", now)]
    db_path = _make_db(tmp_path, [stale] + batch)

    result = detect_failed_logins_from_db(batch, _cfg(threshold=2), db_path, "host-1")
    assert result == []


def test_dedup_suppresses_second_violation_same_window(tmp_path):
    """An existing violation for the same user/host/window suppresses a new one."""
    now = datetime.now()
    events = [
        _evt("alice", now - timedelta(minutes=3)),
        _evt("alice", now - timedelta(minutes=2)),
        _evt("alice", now),
    ]
    db_path = _make_db(tmp_path, events)

    insert_violation({
        "violation_type": "failed_logins",
        "timestamp": now - timedelta(minutes=2),
        "username": "alice",
        "source_ip": "10.0.0.1",
        "resource": None,
        "detail": "2 failed logins in 10 min for user 'alice'",
        "source_host": "host-1",
    }, db_path)

    result = detect_failed_logins_from_db(
        [events[-1]], _cfg(threshold=2), db_path, "host-1"
    )
    assert result == []


def test_different_usernames_not_mixed(tmp_path):
    """User A has 3 failures, user B has 1 — only A crosses the threshold."""
    now = datetime.now()
    events = [
        _evt("attacker-target", now - timedelta(minutes=2)),
        _evt("attacker-target", now - timedelta(minutes=1)),
        _evt("attacker-target", now),
        _evt("innocent", now),
    ]
    db_path = _make_db(tmp_path, events)

    result = detect_failed_logins_from_db(
        events[-2:], _cfg(threshold=2), db_path, "host-1"
    )
    assert len(result) == 1
    assert result[0]["username"] == "attacker-target"


def test_different_source_hosts_not_mixed(tmp_path):
    """The same username on two hosts is counted per host, not pooled."""
    now = datetime.now()
    events = [
        _evt("admin", now - timedelta(minutes=1), host="web-01"),
        _evt("admin", now, host="web-01"),
        _evt("admin", now, host="db-02"),
    ]
    db_path = _make_db(tmp_path, events)

    result = detect_failed_logins_from_db(events, _cfg(threshold=2), db_path, "web-01")
    assert len(result) == 1
    assert result[0]["source_host"] == "web-01"
