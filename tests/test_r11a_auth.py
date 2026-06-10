"""R11-A tests — ingest endpoint authentication, payload limits, host validation.

Endpoint tests override the module-level _EXPECTED_KEY directly (no config
patching).  Agent tests mock requests.post and assert on the headers kwarg.
"""
from unittest.mock import MagicMock, patch

import pytest

import server.ingest_endpoint as _ie
from server.ingest_endpoint import ingest_app
from src.agent.agent import CyberMonAgent

_TEST_KEY = "r11a-secret"


@pytest.fixture(autouse=True)
def _set_api_key():
    old = _ie._EXPECTED_KEY
    _ie._EXPECTED_KEY = _TEST_KEY
    yield
    _ie._EXPECTED_KEY = old


@pytest.fixture
def client():
    ingest_app.config["TESTING"] = True
    with ingest_app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def test_missing_api_key_returns_401(client):
    resp = client.post("/ingest", json={"host": "agent-1", "lines": []})
    assert resp.status_code == 401


def test_wrong_api_key_returns_401(client):
    resp = client.post(
        "/ingest",
        headers={"X-API-Key": "wrong-key"},
        json={"host": "agent-1", "lines": []},
    )
    assert resp.status_code == 401


def test_correct_api_key_accepted(client):
    resp = client.post(
        "/ingest",
        headers={"X-API-Key": _TEST_KEY},
        json={"host": "agent-1", "lines": []},
    )
    assert resp.status_code == 200


def test_empty_string_key_returns_401(client):
    """Even when the expected key is empty, an empty received key is rejected."""
    _ie._EXPECTED_KEY = ""
    resp = client.post(
        "/ingest",
        headers={"X-API-Key": ""},
        json={"host": "agent-1", "lines": []},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Payload limits
# ---------------------------------------------------------------------------

def test_payload_too_large_returns_413(client):
    big_line = "x" * 1024
    resp = client.post(
        "/ingest",
        headers={"X-API-Key": _TEST_KEY},
        json={"host": "agent-1", "lines": [big_line] * 2100},  # > 2MB body
    )
    assert resp.status_code == 413


def test_batch_over_5000_lines_returns_413(client):
    resp = client.post(
        "/ingest",
        headers={"X-API-Key": _TEST_KEY},
        json={"host": "agent-1", "lines": ["x"] * 5001},
    )
    assert resp.status_code == 413


# ---------------------------------------------------------------------------
# Host identifier validation
# ---------------------------------------------------------------------------

def test_invalid_host_chars_returns_400(client):
    resp = client.post(
        "/ingest",
        headers={"X-API-Key": _TEST_KEY},
        json={"host": "evil; DROP TABLE--", "lines": []},
    )
    assert resp.status_code == 400


def test_host_too_long_returns_400(client):
    resp = client.post(
        "/ingest",
        headers={"X-API-Key": _TEST_KEY},
        json={"host": "h" * 65, "lines": []},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Agent sends the key
# ---------------------------------------------------------------------------

def _make_agent(tmp_path, **kwargs) -> CyberMonAgent:
    defaults = dict(
        server_ip="127.0.0.1",
        server_port=5001,
        log_path=str(tmp_path / "auth.log"),
        host_id="test-host",
        retry_attempts=1,
        retry_delay_seconds=0,
    )
    defaults.update(kwargs)
    return CyberMonAgent(**defaults)


def test_agent_sends_api_key_header(tmp_path):
    agent = _make_agent(tmp_path, api_key="my-secret-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"received": 1, "violations_detected": 0}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        agent._post_lines(["line"])

    headers = mock_post.call_args.kwargs["headers"]
    assert headers["X-API-Key"] == "my-secret-key"


def test_agent_missing_key_sends_empty_header(tmp_path):
    agent = _make_agent(tmp_path)   # no api_key — defaults to ""

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"received": 1, "violations_detected": 0}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        agent._post_lines(["line"])

    headers = mock_post.call_args.kwargs["headers"]
    assert headers["X-API-Key"] == ""
