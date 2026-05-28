import os
import pytest
import yaml

from src.storage.db import init_db
from src.storage.writer import insert_events, insert_violation, insert_risk_score
from src.storage.reader import (
    get_all_violations_with_scores,
    get_summary_counts,
    get_violation_detail,
    get_trend_data,
)

TEST_DB = "data/test_phase4.db"


@pytest.fixture
def config():
    with open("config/config.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture
def db_path():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    yield TEST_DB
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


@pytest.fixture
def populated_db(db_path, config):
    from src.ingestion.preprocessor import preprocess_log_file
    from src.detection.detector import run_detection
    from src.scoring.scorer import score_all_violations

    init_db(db_path)
    events = (preprocess_log_file("logs/samples/auth.log", "auth") +
              preprocess_log_file("logs/samples/access.log", "web"))
    insert_events(events, db_path)

    violations = run_detection(events, config)
    scored = score_all_violations(violations, config)
    for v in scored:
        vid = insert_violation(v, db_path)
        insert_risk_score(vid, v, db_path)

    return db_path, len(scored), scored


# --- init_db ---

def test_init_db_creates_tables(db_path):
    init_db(db_path)
    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    conn.close()
    assert {"events", "violations", "risk_scores"}.issubset(tables)


def test_init_db_idempotent(db_path):
    init_db(db_path)
    init_db(db_path)  # must not raise or duplicate tables


def test_init_db_creates_data_dir(tmp_path):
    path = str(tmp_path / "subdir" / "test.db")
    init_db(path)
    assert os.path.exists(path)


# --- insert_events ---

def test_insert_events_batch(db_path):
    from src.ingestion.preprocessor import preprocess_log_file
    init_db(db_path)
    events = preprocess_log_file("logs/samples/auth.log", "auth")
    insert_events(events, db_path)

    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM events")
    count = cur.fetchone()[0]
    conn.close()
    assert count == len(events)


# --- insert_violation ---

def test_insert_violation_returns_int_id(db_path, config):
    from src.ingestion.preprocessor import preprocess_log_file
    from src.detection.detector import run_detection
    from src.scoring.scorer import score_all_violations

    init_db(db_path)
    events = (preprocess_log_file("logs/samples/auth.log", "auth") +
              preprocess_log_file("logs/samples/access.log", "web"))
    violations = run_detection(events, config)
    scored = score_all_violations(violations, config)

    vid = insert_violation(scored[0], db_path)
    assert isinstance(vid, int)
    assert vid >= 1


def test_insert_violation_ids_are_sequential(db_path, config):
    from src.ingestion.preprocessor import preprocess_log_file
    from src.detection.detector import run_detection
    from src.scoring.scorer import score_all_violations

    init_db(db_path)
    events = (preprocess_log_file("logs/samples/auth.log", "auth") +
              preprocess_log_file("logs/samples/access.log", "web"))
    violations = run_detection(events, config)
    scored = score_all_violations(violations, config)

    ids = [insert_violation(v, db_path) for v in scored[:3]]
    assert ids == sorted(ids)
    assert len(set(ids)) == 3


# --- get_all_violations_with_scores ---

def test_get_all_violations_ordered_by_risk_score_desc(populated_db):
    db_path, _, _ = populated_db
    results = get_all_violations_with_scores(db_path)
    scores = [r["risk_score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_get_all_violations_count_matches_inserted(populated_db):
    db_path, total, _ = populated_db
    results = get_all_violations_with_scores(db_path)
    assert len(results) == total


def test_get_all_violations_has_expected_keys(populated_db):
    db_path, _, _ = populated_db
    results = get_all_violations_with_scores(db_path)
    required = {"id", "violation_type", "timestamp", "username", "source_ip",
                "resource", "detail", "likelihood", "impact", "risk_score", "severity"}
    for row in results:
        assert required.issubset(set(row.keys()))


# --- get_summary_counts ---

def test_get_summary_counts_total(populated_db):
    db_path, total, _ = populated_db
    summary = get_summary_counts(db_path)
    assert summary["total"] == total


def test_get_summary_counts_by_type_keys(populated_db):
    db_path, _, _ = populated_db
    summary = get_summary_counts(db_path)
    assert set(summary["by_type"].keys()) == {"failed_logins", "unauthorized_access", "off_hours_login"}


def test_get_summary_counts_by_severity_keys(populated_db):
    db_path, _, _ = populated_db
    summary = get_summary_counts(db_path)
    assert set(summary["by_severity"].keys()) == {"Low", "Medium", "High", "Critical"}


def test_get_summary_counts_by_type_sum_equals_total(populated_db):
    db_path, total, _ = populated_db
    summary = get_summary_counts(db_path)
    assert sum(summary["by_type"].values()) == total


def test_get_summary_counts_by_severity_sum_equals_total(populated_db):
    db_path, total, _ = populated_db
    summary = get_summary_counts(db_path)
    assert sum(summary["by_severity"].values()) == total


# --- get_violation_detail ---

def test_get_violation_detail_returns_dict(populated_db):
    db_path, _, _ = populated_db
    detail = get_violation_detail(1, db_path)
    assert isinstance(detail, dict)
    assert detail.get("id") == 1


def test_get_violation_detail_missing_id_returns_empty(populated_db):
    db_path, _, _ = populated_db
    detail = get_violation_detail(99999, db_path)
    assert detail == {}


def test_get_violation_detail_has_score_fields(populated_db):
    db_path, _, _ = populated_db
    detail = get_violation_detail(1, db_path)
    for key in ("likelihood", "impact", "risk_score", "severity"):
        assert key in detail


# --- get_trend_data ---

def test_get_trend_data_returns_list(populated_db):
    db_path, _, _ = populated_db
    trend = get_trend_data(db_path, days=30)
    assert isinstance(trend, list)


def test_get_trend_data_entries_have_date_and_count(populated_db):
    db_path, _, _ = populated_db
    trend = get_trend_data(db_path, days=30)
    for entry in trend:
        assert "date" in entry
        assert "count" in entry
        assert isinstance(entry["count"], int)


def test_get_trend_data_count_positive(populated_db):
    db_path, _, _ = populated_db
    trend = get_trend_data(db_path, days=30)
    assert len(trend) >= 1
    assert all(entry["count"] > 0 for entry in trend)


# --- no data persists after fixture cleanup ---

def test_test_db_cleaned_up():
    assert not os.path.exists(TEST_DB)
