"""Tests for the ingest endpoint (server/ingest_endpoint.py)."""
import os
import sqlite3
from datetime import datetime
from unittest.mock import patch

import pytest
import yaml

import server.ingest_endpoint as _ie
from server.ingest_endpoint import ingest_app

# All requests in this file authenticate with a known test key (R11-A).
_TEST_KEY = "test-api-key"
_AUTH = {"X-API-Key": _TEST_KEY}


@pytest.fixture(autouse=True)
def _set_api_key():
    """Override the module-level expected key for every test in this file."""
    old = _ie._EXPECTED_KEY
    _ie._EXPECTED_KEY = _TEST_KEY
    yield
    _ie._EXPECTED_KEY = old


def _now_stamp() -> str:
    """Syslog-style timestamp for the current moment.

    Failed-login detection is stateful (R11-B): it counts events within the
    configured window measured from wall-clock now, so test log lines must
    carry current timestamps to land inside the window.
    """
    return datetime.now().strftime("%b %d %H:%M:%S")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config():
    with open("config/config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture
def client():
    """Basic test client using the real project database."""
    ingest_app.config["TESTING"] = True
    with ingest_app.test_client() as c:
        yield c


@pytest.fixture
def isolated_client(tmp_path, config):
    """Test client with a fresh temp database so tests don't pollute data/cybermon.db."""
    db_path = str(tmp_path / "ingest_test.db")
    patched = {**config, "storage": {"db_path": db_path}}

    ingest_app.config["TESTING"] = True
    with patch("server.ingest_endpoint._load_config", return_value=patched):
        with ingest_app.test_client() as c:
            yield c, db_path


# ---------------------------------------------------------------------------
# Valid POST — basic response shape
# ---------------------------------------------------------------------------

def test_empty_lines_returns_200(isolated_client):
    client, _ = isolated_client
    resp = client.post("/ingest", headers=_AUTH, json={"host": "agent-1", "lines": []})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["received"] == 0
    assert data["violations_detected"] == 0


def test_unparseable_lines_returns_200(isolated_client):
    """Lines that don't match any log format are silently skipped; 200 is still returned."""
    client, _ = isolated_client
    resp = client.post("/ingest", headers=_AUTH, json={"host": "agent-1", "lines": ["garbage line"]})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "received" in data
    assert "violations_detected" in data


def test_received_count_matches_lines_sent(isolated_client):
    client, _ = isolated_client
    lines = ["garbage line 1", "garbage line 2", "garbage line 3"]
    resp = client.post("/ingest", headers=_AUTH, json={"host": "agent-1", "lines": lines})
    assert resp.status_code == 200
    assert resp.get_json()["received"] == 3


# ---------------------------------------------------------------------------
# Malformed requests — HTTP 400
# ---------------------------------------------------------------------------

def test_missing_host_returns_400(client):
    resp = client.post("/ingest", headers=_AUTH, json={"lines": ["some line"]})
    assert resp.status_code == 400


def test_missing_lines_returns_400(client):
    resp = client.post("/ingest", headers=_AUTH, json={"host": "agent-1"})
    assert resp.status_code == 400


def test_not_json_returns_400(client):
    resp = client.post("/ingest", headers=_AUTH, data="not json", content_type="text/plain")
    assert resp.status_code == 400


def test_empty_body_returns_400(client):
    resp = client.post("/ingest", headers=_AUTH)
    assert resp.status_code == 400


def test_lines_not_a_list_returns_400(client):
    resp = client.post("/ingest", headers=_AUTH, json={"host": "agent-1", "lines": "not a list"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# source_host written correctly from POST body
# ---------------------------------------------------------------------------

def test_source_host_stored_from_post_body(tmp_path, config):
    """Violations created via POST carry the host ID from the request body."""
    db_path = str(tmp_path / "host_test.db")
    patched = {**config, "storage": {"db_path": db_path}}

    # Brute-force: 10 failed SSH logins right now → triggers failed_logins
    lines = [
        f"{_now_stamp()} server sshd[1234]: "
        f"Failed password for bruteman from 10.0.0.1 port 22 ssh2"
        for _ in range(10)
    ]

    ingest_app.config["TESTING"] = True
    with patch("server.ingest_endpoint._load_config", return_value=patched):
        with ingest_app.test_client() as c:
            resp = c.post("/ingest", headers=_AUTH, json={"host": "remote-machine-X", "lines": lines})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["violations_detected"] >= 1

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT source_host FROM violations")
    hosts = {r[0] for r in cur.fetchall()}
    conn.close()

    assert "remote-machine-X" in hosts


def test_events_source_host_matches_post_body(tmp_path, config):
    """Events stored by the ingest endpoint also carry the agent host ID."""
    db_path = str(tmp_path / "events_host_test.db")
    patched = {**config, "storage": {"db_path": db_path}}

    lines = [
        "May 28 10:00:01 server sshd[1234]: Failed password for alice from 1.2.3.4 port 22 ssh2"
    ]

    ingest_app.config["TESTING"] = True
    with patch("server.ingest_endpoint._load_config", return_value=patched):
        with ingest_app.test_client() as c:
            c.post("/ingest", headers=_AUTH, json={"host": "agent-box-7", "lines": lines})

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT source_host FROM events")
    hosts = {r[0] for r in cur.fetchall()}
    conn.close()

    assert "agent-box-7" in hosts


# ---------------------------------------------------------------------------
# End-to-end: POST → pipeline → stored violation
# ---------------------------------------------------------------------------

def test_pipeline_end_to_end_post_to_stored_violation(tmp_path, config):
    """Full pipeline: SSH brute-force lines arrive via POST, violation stored in DB."""
    db_path = str(tmp_path / "e2e.db")
    patched = {**config, "storage": {"db_path": db_path}}

    lines = [
        f"{_now_stamp()} server sshd[1234]: "
        f"Failed password for hacker from 9.9.9.9 port 22 ssh2"
        for _ in range(10)
    ]

    ingest_app.config["TESTING"] = True
    with patch("server.ingest_endpoint._load_config", return_value=patched):
        with ingest_app.test_client() as c:
            resp = c.post("/ingest", headers=_AUTH, json={"host": "attacker-target", "lines": lines})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["received"] == 10
    assert body["violations_detected"] >= 1

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM events")
    event_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM violations")
    violation_count = cur.fetchone()[0]
    conn.close()

    assert event_count == 10
    assert violation_count >= 1


def test_pipeline_web_line_end_to_end(tmp_path, config):
    """Apache access log lines sent via POST are parsed and stored."""
    db_path = str(tmp_path / "web_e2e.db")
    patched = {**config, "storage": {"db_path": db_path}}

    lines = [
        '10.0.0.50 - - [28/May/2026:10:00:01 +0000] "GET /admin HTTP/1.1" 403 512 "-" "curl/7.0"',
    ]

    ingest_app.config["TESTING"] = True
    with patch("server.ingest_endpoint._load_config", return_value=patched):
        with ingest_app.test_client() as c:
            resp = c.post("/ingest", headers=_AUTH, json={"host": "web-agent", "lines": lines})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["received"] == 1

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM events")
    count = cur.fetchone()[0]
    conn.close()
    assert count == 1


# ---------------------------------------------------------------------------
# R11-B: stateful detection across batches
# ---------------------------------------------------------------------------

def test_slow_brute_force_detected_across_batches(tmp_path, config):
    """One failed login per batch — batch-only detection misses this entirely.

    With DB-window detection (threshold=2), the second batch must produce a
    violation because the first batch's event is still inside the window.
    """
    db_path = str(tmp_path / "slow_brute.db")
    patched = {**config, "storage": {"db_path": db_path}}

    def _line() -> str:
        return (f"{_now_stamp()} server sshd[1234]: "
                f"Failed password for victim from 6.6.6.6 port 22 ssh2")

    ingest_app.config["TESTING"] = True
    with patch("server.ingest_endpoint._load_config", return_value=patched):
        with ingest_app.test_client() as c:
            first = c.post("/ingest", headers=_AUTH,
                           json={"host": "slow-agent", "lines": [_line()]})
            second = c.post("/ingest", headers=_AUTH,
                            json={"host": "slow-agent", "lines": [_line()]})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.get_json()["violations_detected"] >= 1
