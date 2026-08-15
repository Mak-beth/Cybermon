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
    get_trend_by_hour_today,
    get_trend_by_day_week,
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
    from datetime import datetime, timedelta
    from src.ingestion.preprocessor import preprocess_log_file
    from src.detection.detector import run_detection
    from src.scoring.scorer import score_all_violations

    init_db(db_path)
    events = (preprocess_log_file("logs/samples/auth.log", "auth") +
              preprocess_log_file("logs/samples/access.log", "web"))

    # The sample logs carry a fixed date, so once the run date is more than
    # get_trend_data's 30-day window past it, the trend query sees nothing.
    # Shift every event forward by whole weeks so the data lands within the
    # last few days of now. Whole-week shifts preserve weekday and time-of-day,
    # leaving off-hours / business-day detection (and thus every violation
    # count) identical — only the calendar position moves.
    if events:
        latest = max(e["timestamp"] for e in events)
        weeks = (datetime.now() - latest).days // 7
        if weeks > 0:
            shift = timedelta(weeks=weeks)
            for e in events:
                e["timestamp"] = e["timestamp"] + shift

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
                "resource", "detail", "source_host", "likelihood", "impact",
                "risk_score", "severity"}
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


# --- get_trend_by_hour_today ---

def test_get_trend_by_hour_today_returns_correct_keys(db_path):
    init_db(db_path)
    result = get_trend_by_hour_today(db_path)
    assert set(result.keys()) == {"hours", "failed_logins", "unauthorized_access", "off_hours_login"}


def test_get_trend_by_hour_today_has_24_hours(db_path):
    init_db(db_path)
    result = get_trend_by_hour_today(db_path)
    assert len(result["hours"]) == 24
    assert result["hours"] == [f"{h:02d}" for h in range(24)]


def test_get_trend_by_hour_today_count_lists_have_24_entries(db_path):
    init_db(db_path)
    result = get_trend_by_hour_today(db_path)
    for key in ("failed_logins", "unauthorized_access", "off_hours_login"):
        assert len(result[key]) == 24


def test_get_trend_by_hour_today_counts_are_non_negative_integers(db_path):
    init_db(db_path)
    result = get_trend_by_hour_today(db_path)
    for key in ("failed_logins", "unauthorized_access", "off_hours_login"):
        for count in result[key]:
            assert isinstance(count, int)
            assert count >= 0


def test_get_trend_by_hour_today_captures_todays_violations(db_path):
    import sqlite3
    from datetime import datetime

    init_db(db_path)
    # Stamp a fixed hour on today's LOCAL date. get_trend_by_hour_today filters
    # on DATE('now','localtime'), so this matches "today" at whatever hour the
    # test runs (the old version used the UTC DATE('now') and failed during the
    # local 00:00-08:00 window on UTC-ahead machines).
    ts = datetime.now().replace(hour=13, minute=30, second=0, microsecond=0)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO violations "
        "(violation_type, timestamp, username, source_ip, resource, detail, source_host) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("unauthorized_access", ts.isoformat(), None, "10.0.0.1", "/admin", "test", "localhost"),
    )
    conn.commit()
    conn.close()

    result = get_trend_by_hour_today(db_path)
    assert result["unauthorized_access"][13] == 1


# --- get_trend_by_day_week ---

def test_get_trend_by_day_week_returns_correct_keys(db_path):
    init_db(db_path)
    result = get_trend_by_day_week(db_path)
    assert set(result.keys()) == {"dates", "failed_logins", "unauthorized_access", "off_hours_login"}


def test_get_trend_by_day_week_has_7_dates(db_path):
    init_db(db_path)
    result = get_trend_by_day_week(db_path)
    assert len(result["dates"]) == 7


def test_get_trend_by_day_week_count_lists_have_7_entries(db_path):
    init_db(db_path)
    result = get_trend_by_day_week(db_path)
    for key in ("failed_logins", "unauthorized_access", "off_hours_login"):
        assert len(result[key]) == 7


def test_get_trend_by_day_week_counts_are_non_negative_integers(db_path):
    init_db(db_path)
    result = get_trend_by_day_week(db_path)
    for key in ("failed_logins", "unauthorized_access", "off_hours_login"):
        for count in result[key]:
            assert isinstance(count, int)
            assert count >= 0


def test_get_trend_by_day_week_today_is_last_date(db_path):
    from datetime import date
    init_db(db_path)
    result = get_trend_by_day_week(db_path)
    assert result["dates"][-1] == date.today().isoformat()


# --- no data persists after fixture cleanup ---

def test_test_db_cleaned_up():
    assert not os.path.exists(TEST_DB)
