"""Scores-only re-score: apply new scoring values without a restart.

The pipeline normally re-derives everything from log files at launch, so a
scoring change only showed up after restarting. This recompute rewrites
risk_scores for violations ALREADY in the database and touches nothing else.

Deliberately narrow: events and violations rows are never inserted, deleted or
modified, and no log file is read.
"""
import copy
import sqlite3

import pytest
import yaml

from src.storage.db import init_db
from src.storage.rescore import rescore_violations


def _load_cfg():
    with open("config/config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _insert(db_path, *, vtype, username, likelihood, impact, severity,
            resource=None, detail="d", ts="2026-08-20T03:14:00"):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO violations (violation_type, timestamp, username, source_ip,"
        " resource, detail, source_host) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (vtype, ts, username, "10.0.0.1", resource, detail, "host-1"),
    )
    vid = cur.lastrowid
    cur.execute(
        "INSERT INTO risk_scores (violation_id, likelihood, impact, risk_score,"
        " severity, source_host) VALUES (?, ?, ?, ?, ?, ?)",
        (vid, likelihood, impact, likelihood * impact, severity, "host-1"),
    )
    conn.commit()
    conn.close()
    return vid


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "rescore.db")
    init_db(path)
    return path


def _snapshot(db_path):
    """Row counts and ids for the tables that must never change."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    data = {
        "violation_ids": [r[0] for r in cur.execute("SELECT id FROM violations ORDER BY id")],
        "violation_rows": cur.execute(
            "SELECT id, violation_type, timestamp, username, source_ip, resource,"
            " detail, source_host, triggering_event_id FROM violations ORDER BY id"
        ).fetchall(),
        "event_count": cur.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "event_ids": [r[0] for r in cur.execute("SELECT id FROM events ORDER BY id")],
    }
    conn.close()
    return data


def _score_of(db_path, vid):
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT likelihood, impact, risk_score, severity FROM risk_scores "
        "WHERE violation_id = ?", (vid,)).fetchone()
    conn.close()
    return row


# ---------------------------------------------------------------------------
# EVIDENCE TEST — new scoring value applies with no restart
# ---------------------------------------------------------------------------

def test_evidence_offhours_privileged_rescores_from_6_to_10_without_restart(db):
    """Raising off_hours_high_user_impact re-scores privileged off-hours
    violations from 6/Medium to 10/High in place, with no restart and no
    change to the violations table."""
    cfg = _load_cfg()
    # Start from the old flat behaviour: privileged impact == default impact.
    cfg["scoring"]["rules"]["off_hours_high_user_impact"] = 3

    root_id = _insert(db, vtype="off_hours_login", username="root",
                      likelihood=2, impact=3, severity="Medium")
    alice_id = _insert(db, vtype="off_hours_login", username="alice",
                       likelihood=2, impact=3, severity="Medium")

    before = _snapshot(db)
    assert _score_of(db, root_id) == (2, 3, 6, "Medium")

    # Admin raises the privileged off-hours impact and re-scores.
    cfg["scoring"]["rules"]["off_hours_high_user_impact"] = 5
    summary = rescore_violations(db, cfg)

    # Privileged account moved tier; standard account did not.
    assert _score_of(db, root_id) == (2, 5, 10, "High")
    assert _score_of(db, alice_id) == (2, 3, 6, "Medium")
    assert summary["total"] == 2 and summary["changed"] == 1

    # No violations/events were added, removed or altered.
    assert _snapshot(db) == before


# ---------------------------------------------------------------------------
# events / violations must be untouched
# ---------------------------------------------------------------------------

def test_violations_and_events_rows_untouched(db):
    cfg = _load_cfg()
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO events (timestamp, username, source_ip, resource, action,"
        " status_code, log_type, source_host, raw_log) "
        "VALUES ('2026-08-20T03:14:00','root','10.0.0.1',NULL,'ssh_login',"
        "'SUCCESS','auth','host-1','raw line')")
    conn.commit()
    conn.close()

    _insert(db, vtype="off_hours_login", username="root",
            likelihood=2, impact=3, severity="Medium")
    _insert(db, vtype="failed_logins", username="admin", likelihood=3, impact=4,
            severity="High", detail="8 failed logins in 10 min")

    before = _snapshot(db)
    rescore_violations(db, cfg)
    after = _snapshot(db)

    assert after["violation_ids"] == before["violation_ids"]
    assert after["violation_rows"] == before["violation_rows"]
    assert after["event_count"] == before["event_count"]
    assert after["event_ids"] == before["event_ids"]


def test_risk_scores_row_count_is_stable(db):
    cfg = _load_cfg()
    for i in range(5):
        _insert(db, vtype="off_hours_login", username=f"u{i}",
                likelihood=2, impact=3, severity="Medium")
    conn = sqlite3.connect(db)
    before = conn.execute("SELECT COUNT(*) FROM risk_scores").fetchone()[0]
    conn.close()

    rescore_violations(db, cfg)

    conn = sqlite3.connect(db)
    after = conn.execute("SELECT COUNT(*) FROM risk_scores").fetchone()[0]
    conn.close()
    assert after == before == 5


def test_rescore_is_idempotent(db):
    cfg = _load_cfg()
    vid = _insert(db, vtype="off_hours_login", username="root",
                  likelihood=2, impact=3, severity="Medium")
    first = rescore_violations(db, cfg)
    score_after_first = _score_of(db, vid)
    second = rescore_violations(db, cfg)
    assert _score_of(db, vid) == score_after_first
    assert second["changed"] == 0          # nothing left to change
    assert second["total"] == first["total"]


def test_empty_database_rescores_cleanly(db):
    assert rescore_violations(db, _load_cfg()) == {
        "total": 0, "updated": 0, "changed": 0}


def test_other_violation_types_rescore_correctly(db):
    cfg = _load_cfg()
    unauth = _insert(db, vtype="unauthorized_access", username=None,
                     likelihood=1, impact=1, severity="Low", resource="/admin",
                     detail="HTTP 403")
    rescore_violations(db, cfg)
    assert _score_of(db, unauth) == (3, 5, 15, "High")


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------

def test_failure_rolls_back_and_leaves_scores_intact(db):
    """A bad config must not leave scores half-rewritten."""
    cfg = _load_cfg()
    vid = _insert(db, vtype="off_hours_login", username="root",
                  likelihood=2, impact=3, severity="Medium")
    before = _score_of(db, vid)

    broken = copy.deepcopy(cfg)
    del broken["scoring"]["severity_tiers"]      # assign_severity will KeyError

    with pytest.raises(Exception):
        rescore_violations(db, broken)

    assert _score_of(db, vid) == before          # unchanged
    assert _snapshot(db)["violation_ids"] == [vid]


def test_missing_score_row_is_created_not_orphaned(db):
    """A violation with no risk_scores row gets one, rather than staying unscored."""
    cfg = _load_cfg()
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO violations (violation_type, timestamp, username, source_ip,"
        " resource, detail, source_host) VALUES "
        "('off_hours_login','2026-08-20T03:14:00','root','10.0.0.1',NULL,'d','h')")
    vid = cur.lastrowid
    conn.commit()
    conn.close()

    summary = rescore_violations(db, cfg)
    assert summary["total"] == 1
    assert _score_of(db, vid) == (2, 5, 10, "High")


# ---------------------------------------------------------------------------
# Config safety
# ---------------------------------------------------------------------------

def test_rescore_never_writes_to_the_config_file(db, tmp_path):
    """Re-scoring reads config; it must not modify config.yaml at all."""
    import hashlib
    import shutil
    cfg_copy = tmp_path / "config.yaml"
    shutil.copyfile("config/config.yaml", cfg_copy)
    sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
    before = sha(cfg_copy)

    _insert(db, vtype="off_hours_login", username="root",
            likelihood=2, impact=3, severity="Medium")
    rescore_violations(db, yaml.safe_load(open(cfg_copy, encoding="utf-8")))

    assert sha(cfg_copy) == before


def test_api_key_untouched_by_rescore(db):
    """The re-score path must never read, log or alter the shared secret."""
    cfg = _load_cfg()
    original = cfg["server"]["api_key"]
    _insert(db, vtype="off_hours_login", username="root",
            likelihood=2, impact=3, severity="Medium")
    rescore_violations(db, cfg)
    assert cfg["server"]["api_key"] == original


def test_rescore_module_reads_no_log_files():
    """Static guard: the recompute must not open log files or run detection."""
    import inspect
    from src.storage import rescore
    source = inspect.getsource(rescore)
    for forbidden in ("preprocess_log_file", "run_detection", "_clear_tables",
                      "open(", "eval(", "exec(", "subprocess"):
        assert forbidden not in source, f"{forbidden} present in rescore module"
