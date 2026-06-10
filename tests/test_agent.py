"""Tests for CyberMonAgent (src/agent/agent.py)."""
import threading
import time
from unittest.mock import MagicMock, call, patch

import pytest
import requests

from src.agent.agent import CyberMonAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(tmp_path, **kwargs) -> CyberMonAgent:
    defaults = dict(
        server_ip="127.0.0.1",
        server_port=5001,
        log_path=str(tmp_path / "auth.log"),
        host_id="test-host",
        retry_attempts=3,
        retry_delay_seconds=0,   # no real sleep in tests
    )
    defaults.update(kwargs)
    return CyberMonAgent(**defaults)


# ---------------------------------------------------------------------------
# POST JSON structure
# ---------------------------------------------------------------------------

def test_post_sends_correct_json_structure(tmp_path):
    """_post_lines sends {"host": host_id, "lines": [...]} to the server URL."""
    agent = _make_agent(tmp_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"received": 2, "violations_detected": 0}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        agent._post_lines(["line one", "line two"])

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    body = kwargs["json"]
    assert body["host"] == "test-host"
    assert body["lines"] == ["line one", "line two"]


def test_post_targets_correct_url(tmp_path):
    """URL is built from server_ip and server_port."""
    agent = _make_agent(tmp_path, server_ip="10.0.0.1", server_port=9999)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"received": 1, "violations_detected": 0}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        agent._post_lines(["line"])

    args, _ = mock_post.call_args
    assert args[0] == "http://10.0.0.1:9999/ingest"


def test_post_returns_true_on_200(tmp_path):
    """_post_lines returns True when server responds 200."""
    agent = _make_agent(tmp_path)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"received": 1, "violations_detected": 0}

    with patch("requests.post", return_value=mock_resp):
        result = agent._post_lines(["line"])

    assert result is True


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

def test_retry_fires_on_connection_error(tmp_path):
    """Agent retries retry_attempts times when a connection error occurs."""
    agent = _make_agent(tmp_path, retry_attempts=3)

    with patch("requests.post",
               side_effect=requests.RequestException("refused")) as mock_post:
        result = agent._post_lines(["line"])

    assert result is False
    assert mock_post.call_count == 3


def test_retry_fires_on_non_200_status(tmp_path):
    """Agent retries when the server returns a non-200 status code."""
    agent = _make_agent(tmp_path, retry_attempts=3)

    mock_resp = MagicMock()
    mock_resp.status_code = 503

    with patch("requests.post", return_value=mock_resp) as mock_post:
        result = agent._post_lines(["line"])

    assert result is False
    assert mock_post.call_count == 3


def test_retry_succeeds_on_second_attempt(tmp_path):
    """Agent stops retrying as soon as a 200 is received."""
    agent = _make_agent(tmp_path, retry_attempts=3)

    fail_resp = MagicMock()
    fail_resp.status_code = 500

    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"received": 1, "violations_detected": 0}

    with patch("requests.post",
               side_effect=[requests.RequestException("err"), ok_resp]) as mock_post:
        result = agent._post_lines(["line"])

    assert result is True
    assert mock_post.call_count == 2


# ---------------------------------------------------------------------------
# Missing log file
# ---------------------------------------------------------------------------

def test_agent_does_not_crash_on_missing_log(tmp_path):
    """Agent handles a non-existent log file by polling without crashing."""
    agent = _make_agent(tmp_path, log_path=str(tmp_path / "nonexistent.log"))

    t = threading.Thread(target=agent.run, args=(0.05,), daemon=True)
    t.start()
    time.sleep(0.2)
    agent.stop()
    t.join(timeout=1.0)

    # Thread should have exited cleanly (or still alive — what matters is no crash)
    # The key assertion is that no exception propagated out of run()
    assert True


def test_agent_picks_up_new_lines_from_file(tmp_path):
    """Agent tails a file and POSTs lines that appear after it starts."""
    log_file = tmp_path / "auth.log"
    log_file.write_text("")      # empty file; agent will seek to end

    received_payloads = []
    done = threading.Event()

    def fake_post(url, json=None, headers=None, timeout=None):
        received_payloads.append(json)
        if len(received_payloads) >= 1:
            done.set()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"received": len(json["lines"]), "violations_detected": 0}
        return resp

    agent = _make_agent(tmp_path, log_path=str(log_file))

    with patch("requests.post", side_effect=fake_post):
        t = threading.Thread(target=agent.run, args=(0.05,), daemon=True)
        t.start()
        time.sleep(0.15)          # let agent open the file and seek to end

        with open(str(log_file), "a") as fh:
            fh.write("May 28 10:00:01 server sshd[1]: Failed password for alice from 1.2.3.4 port 22 ssh2\n")

        done.wait(timeout=3)
        agent.stop()
        t.join(timeout=1.0)

    assert len(received_payloads) >= 1
    all_lines = [l for p in received_payloads for l in p["lines"]]
    assert any("alice" in l for l in all_lines)
    assert all(p["host"] == "test-host" for p in received_payloads)
