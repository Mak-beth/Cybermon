"""Sort / prioritisation of violations — FYP Objective 3 evidence.

Objective 3: "prioritizes detected violations into four severity tiers".
The scoring model answers "which of these matters most?" via
risk_score = likelihood x impact (1-25); these tests pin the ordering the
Violations tab uses to surface that.

Data layer only — src.gui.data_access imports no Qt, so these run headless.
"""
import sqlite3

import pytest

from src.gui import data_access
from src.gui.data_access import (
    DEFAULT_SORT,
    SORT_NEWEST,
    SORT_RISK_ASC,
    SORT_RISK_DESC,
    SORT_RISK_DESC_OLDEST,
    get_all_violations,
)
from src.storage.db import init_db


@pytest.fixture
def sort_db(tmp_path, monkeypatch):
    """Temp database wired into data_access's cached path."""
    db_path = str(tmp_path / "sort.db")
    init_db(db_path)
    # data_access caches the resolved path in a module-level global.
    monkeypatch.setattr(data_access, "_db_path", db_path)
    return db_path


def _insert(db_path, *, vtype, ts, likelihood, impact, severity,
            username=None, resource=None, host="localhost"):
    """Insert one violation + its risk score. Returns the violation id."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO violations (violation_type, timestamp, username, source_ip,"
        " resource, detail, source_host) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (vtype, ts, username, "10.0.0.1", resource, "test", host),
    )
    vid = cur.lastrowid
    cur.execute(
        "INSERT INTO risk_scores (violation_id, likelihood, impact, risk_score,"
        " severity, source_host) VALUES (?, ?, ?, ?, ?, ?)",
        (vid, likelihood, impact, likelihood * impact, severity, host),
    )
    conn.commit()
    conn.close()
    return vid


# ---------------------------------------------------------------------------
# Objective 3 evidence — the supervisor's scenario
# ---------------------------------------------------------------------------

def test_objective3_simultaneous_violations_are_prioritised_by_risk_score(sort_db):
    """Three violations at the SAME timestamp -> highest risk is surfaced first.

    This is the answer to "if three violations arrive at the same time, which
    one is prioritized?": the risk score decides, not arrival order.
    """
    same_ts = "2026-08-20T10:00:00"
    _insert(sort_db, vtype="unauthorized_access", ts=same_ts,
            likelihood=3, impact=5, severity="High", resource="/admin")      # 15
    _insert(sort_db, vtype="failed_logins", ts=same_ts,
            likelihood=4, impact=4, severity="High", username="admin")       # 16
    _insert(sort_db, vtype="off_hours_login", ts=same_ts,
            likelihood=2, impact=3, severity="Medium")                       # 6

    rows = get_all_violations(sort=SORT_RISK_DESC)

    assert [r["violation_type"] for r in rows] == [
        "failed_logins",         # 16 — highest risk
        "unauthorized_access",   # 15
        "off_hours_login",       # 6
    ]
    assert [r["risk_score"] for r in rows] == [16, 15, 6]
    assert [r["severity"] for r in rows] == ["High", "High", "Medium"]


# ---------------------------------------------------------------------------
# The four sort modes
# ---------------------------------------------------------------------------

@pytest.fixture
def three_scores(sort_db):
    """Low/high scores across two timestamps for ordering assertions."""
    ids = {
        "old_high":  _insert(sort_db, vtype="failed_logins", ts="2026-08-20T09:00:00",
                             likelihood=4, impact=4, severity="High"),        # 16
        "new_high":  _insert(sort_db, vtype="unauthorized_access", ts="2026-08-20T11:00:00",
                             likelihood=4, impact=4, severity="High"),        # 16
        "new_low":   _insert(sort_db, vtype="off_hours_login", ts="2026-08-20T12:00:00",
                             likelihood=2, impact=3, severity="Medium"),      # 6
    }
    return sort_db, ids


def test_sort_highest_risk_first(three_scores):
    _db, ids = three_scores
    rows = get_all_violations(sort=SORT_RISK_DESC)
    # both 16s first (newest of them first), then the 6
    assert [r["id"] for r in rows] == [ids["new_high"], ids["old_high"], ids["new_low"]]


def test_sort_highest_risk_oldest_first(three_scores):
    _db, ids = three_scores
    rows = get_all_violations(sort=SORT_RISK_DESC_OLDEST)
    # same risk tier, but oldest within the tier leads
    assert [r["id"] for r in rows] == [ids["old_high"], ids["new_high"], ids["new_low"]]


def test_sort_lowest_risk_first(three_scores):
    _db, ids = three_scores
    rows = get_all_violations(sort=SORT_RISK_ASC)
    assert rows[0]["id"] == ids["new_low"]
    assert [r["risk_score"] for r in rows] == [6, 16, 16]


def test_sort_newest_first(three_scores):
    _db, ids = three_scores
    rows = get_all_violations(sort=SORT_NEWEST)
    assert [r["id"] for r in rows] == [ids["new_low"], ids["new_high"], ids["old_high"]]


# ---------------------------------------------------------------------------
# Determinism, default, empty state
# ---------------------------------------------------------------------------

def test_tie_breaking_is_deterministic_across_repeated_calls(sort_db):
    """Identical risk_score AND timestamp -> id decides, stably.

    off_hours_login always scores exactly 6, so large tie groups are guaranteed
    in real data; without a tie-break, rows would visibly shuffle on refresh.
    """
    same_ts = "2026-08-20T10:00:00"
    ids = [
        _insert(sort_db, vtype="off_hours_login", ts=same_ts,
                likelihood=2, impact=3, severity="Medium")
        for _ in range(6)
    ]

    first = [r["id"] for r in get_all_violations(sort=SORT_RISK_DESC)]
    for _ in range(5):
        assert [r["id"] for r in get_all_violations(sort=SORT_RISK_DESC)] == first
    # deterministic AND explicitly id-ordered (descending for this mode)
    assert first == sorted(ids, reverse=True)


def test_default_sort_preserves_pre_existing_behaviour(three_scores):
    """No sort argument -> unchanged newest-first ordering for existing callers."""
    _db, _ids = three_scores
    assert DEFAULT_SORT == SORT_NEWEST
    assert get_all_violations() == get_all_violations(sort=SORT_NEWEST)


def test_empty_database_returns_empty_list_for_every_sort(sort_db):
    for key in (SORT_RISK_DESC, SORT_RISK_DESC_OLDEST, SORT_RISK_ASC, SORT_NEWEST, None):
        assert get_all_violations(sort=key) == []


def test_sort_composes_with_host_filter(sort_db):
    """The sort control must not bypass the existing Host filter."""
    same_ts = "2026-08-20T10:00:00"
    _insert(sort_db, vtype="failed_logins", ts=same_ts, likelihood=4, impact=4,
            severity="High", host="host-a")                                   # 16
    keep = _insert(sort_db, vtype="unauthorized_access", ts=same_ts,
                   likelihood=3, impact=5, severity="High", host="host-b")    # 15
    _insert(sort_db, vtype="off_hours_login", ts=same_ts, likelihood=2, impact=3,
            severity="Medium", host="host-b")                                 # 6

    rows = get_all_violations(host_filter="host-b", sort=SORT_RISK_DESC)
    assert [r["id"] for r in rows][0] == keep
    assert all(r["source_host"] == "host-b" for r in rows)
    assert [r["risk_score"] for r in rows] == [15, 6]


def test_unknown_sort_key_falls_back_to_default(three_scores):
    """A bad key must not raise or inject SQL — it falls back to the default."""
    _db, _ids = three_scores
    assert get_all_violations(sort="'; DROP TABLE violations; --") == \
        get_all_violations(sort=DEFAULT_SORT)
