import json
import queue as queue_module
import pytest
import yaml

from src.dashboard.app import app, post_violation, _violation_queue, _sse_generator, _SSE_STOP


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


@pytest.fixture
def client(pipeline_result):
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# /live page
# ---------------------------------------------------------------------------

def test_live_returns_200(client):
    resp = client.get("/live")
    assert resp.status_code == 200


def test_live_shows_existing_violations(client):
    resp = client.get("/live")
    body = resp.data.decode("utf-8")
    # The page should include at least one violation type from the seeded DB
    assert "failed_logins" in body or "unauthorized_access" in body or "off_hours_login" in body


# ---------------------------------------------------------------------------
# /stream route — _SSE_STOP sentinel makes the generator finite so the test
# client can drain it without blocking on the 30 s keepalive timeout
# ---------------------------------------------------------------------------

def _drain_queue():
    while not _violation_queue.empty():
        try:
            _violation_queue.get_nowait()
        except queue_module.Empty:
            break


def test_stream_returns_200(pipeline_result):
    app.config["TESTING"] = True
    _drain_queue()
    _violation_queue.put(_SSE_STOP)  # generator exits immediately
    with app.test_client() as client:
        resp = client.get("/stream")
        assert resp.status_code == 200


def test_stream_content_type_is_event_stream(pipeline_result):
    app.config["TESTING"] = True
    _drain_queue()
    _violation_queue.put(_SSE_STOP)
    with app.test_client() as client:
        resp = client.get("/stream")
        assert "text/event-stream" in resp.content_type


def test_stream_delivers_violation_data(pipeline_result):
    app.config["TESTING"] = True
    _drain_queue()
    v = {
        "violation_type": "failed_logins",
        "timestamp": "2026-05-28 10:00:00",
        "username": "attacker",
        "source_ip": "10.0.0.1",
        "resource": None,
        "detail": "6 failed logins",
        "likelihood": 3,
        "impact": 4,
        "risk_score": 12,
        "severity": "High",
    }
    post_violation(v)
    _violation_queue.put(_SSE_STOP)
    with app.test_client() as client:
        resp = client.get("/stream")
        body = resp.data.decode("utf-8")
    assert "data:" in body
    data_line = next(l for l in body.splitlines() if l.startswith("data:"))
    payload = json.loads(data_line[5:].strip())
    assert payload["violation_type"] == "failed_logins"


# ---------------------------------------------------------------------------
# post_violation → queue
# ---------------------------------------------------------------------------

def test_post_violation_enqueues_item():
    # Drain any leftover items from previous tests
    while not _violation_queue.empty():
        try:
            _violation_queue.get_nowait()
        except queue_module.Empty:
            break

    v = {
        "violation_type": "failed_logins",
        "timestamp": "2026-05-28 10:00:00",
        "username": "testuser",
        "source_ip": "10.0.0.1",
        "resource": None,
        "detail": "6 failed logins in 10 minutes",
        "likelihood": 3,
        "impact": 4,
        "risk_score": 12,
        "severity": "High",
    }
    post_violation(v)
    result = _violation_queue.get(timeout=1)
    assert result["violation_type"] == "failed_logins"
    assert result["risk_score"] == 12


# ---------------------------------------------------------------------------
# _sse_generator — test SSE data format directly, no HTTP overhead
# ---------------------------------------------------------------------------

def test_sse_generator_yields_violation_as_sse_data():
    q = queue_module.Queue()
    v = {
        "violation_type": "unauthorized_access",
        "timestamp": "2026-05-28 11:00:00",
        "username": None,
        "source_ip": "10.0.0.2",
        "resource": "/admin",
        "detail": "HTTP 403",
        "likelihood": 3,
        "impact": 5,
        "risk_score": 15,
        "severity": "High",
    }
    q.put(v)

    gen = _sse_generator(q)
    chunk = next(gen)  # generator suspends after this yield — no hang

    assert chunk.startswith("data: ")
    assert chunk.endswith("\n\n")
    payload = json.loads(chunk[6:].strip())
    assert payload["violation_type"] == "unauthorized_access"
    assert payload["risk_score"] == 15


def test_sse_generator_formats_datetime_fields():
    from datetime import datetime
    q = queue_module.Queue()
    v = {
        "violation_type": "off_hours_login",
        "timestamp": datetime(2026, 5, 28, 2, 14, 0),
        "username": "alice",
        "source_ip": "10.0.0.3",
        "resource": None,
        "detail": "login at 02:14",
        "likelihood": 2,
        "impact": 3,
        "risk_score": 6,
        "severity": "Medium",
    }
    q.put(v)

    gen = _sse_generator(q)
    chunk = next(gen)

    payload = json.loads(chunk[6:].strip())
    assert payload["username"] == "alice"
    assert "2026" in payload["timestamp"]  # datetime serialized as string
