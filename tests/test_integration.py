import os
import sqlite3
import pytest
import yaml


@pytest.fixture
def config():
    with open("config/config.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture
def pipeline_result(config):
    from main import run_pipeline
    result = run_pipeline(
        "logs/samples/auth.log",
        "logs/samples/access.log",
        config,
    )
    yield result


# --- pipeline correctness ---

def test_pipeline_events_parsed(pipeline_result):
    assert len(pipeline_result["events"]) == 70


def test_pipeline_violations_detected(pipeline_result):
    assert len(pipeline_result["scored"]) == 13


def test_pipeline_all_three_types_present(pipeline_result):
    vtypes = {v["violation_type"] for v in pipeline_result["scored"]}
    assert vtypes == {"failed_logins", "unauthorized_access", "off_hours_login"}


def test_pipeline_violations_in_db_match_detection(pipeline_result, config):
    from src.storage.reader import get_summary_counts
    db_path = config["storage"]["db_path"]
    summary = get_summary_counts(db_path)
    assert summary["total"] == len(pipeline_result["scored"])


def test_pipeline_scored_all_have_severity(pipeline_result):
    assert all(v["severity"] in ("Low", "Medium", "High", "Critical")
               for v in pipeline_result["scored"])


def test_pipeline_risk_score_equals_product(pipeline_result):
    assert all(v["risk_score"] == v["likelihood"] * v["impact"]
               for v in pipeline_result["scored"])


# --- idempotency: running twice produces the same count, not double ---

def test_pipeline_idempotent(config):
    from main import run_pipeline
    from src.storage.reader import get_summary_counts

    run_pipeline("logs/samples/auth.log", "logs/samples/access.log", config)
    count_after_first = get_summary_counts(config["storage"]["db_path"])["total"]

    run_pipeline("logs/samples/auth.log", "logs/samples/access.log", config)
    count_after_second = get_summary_counts(config["storage"]["db_path"])["total"]

    assert count_after_first == count_after_second


