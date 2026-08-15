import pytest
from datetime import datetime

from src.ingestion.reader import read_log_file
from src.ingestion.parser import parse_auth_log_line, parse_access_log_line
from src.ingestion.preprocessor import preprocess_log_file

SCHEMA_KEYS = {"timestamp", "username", "source_ip", "resource", "action", "status_code"}


# --- reader ---

def test_reader_returns_nonempty_lines():
    lines = read_log_file("logs/samples/auth.log")
    assert len(lines) > 0
    assert all(line.strip() for line in lines)


def test_reader_raises_on_missing_file():
    with pytest.raises(FileNotFoundError):
        read_log_file("nonexistent_file.log")


# --- parser: auth ---

def test_parse_auth_returns_none_on_blank():
    assert parse_auth_log_line("") is None
    assert parse_auth_log_line("   ") is None


def test_parse_auth_returns_none_on_malformed():
    assert parse_auth_log_line("this is not a log line at all") is None


def test_parse_auth_failed_line():
    line = "May 27 09:10:01 server sshd[1001]: Failed password for admin from 192.168.1.100 port 22 ssh2"
    result = parse_auth_log_line(line)
    assert result is not None
    assert result["username"] == "admin"
    assert result["source_ip"] == "192.168.1.100"
    assert result["status"] == "failure"


def test_parse_auth_invalid_user_line():
    line = "May 27 11:05:33 server sshd[1041]: Failed password for invalid user guest from 198.51.100.1 port 22 ssh2"
    result = parse_auth_log_line(line)
    assert result is not None
    assert result["username"] == "guest"
    assert result["status"] == "failure"


def test_parse_auth_accepted_line():
    line = "May 27 10:22:05 server sshd[1020]: Accepted password for john from 10.0.0.5 port 22 ssh2"
    result = parse_auth_log_line(line)
    assert result is not None
    assert result["username"] == "john"
    assert result["source_ip"] == "10.0.0.5"
    assert result["status"] == "success"


# --- parser: auth (Windows OpenSSH file-log format) ---

def test_parse_auth_windows_failed_password():
    line = "6376 2026-08-16 03:17:28.251 Failed password for invalid user faketestuser from ::1 port 51785 ssh2"
    result = parse_auth_log_line(line)
    assert result is not None
    assert result["timestamp"] == "2026-08-16 03:17:28.251"
    assert result["hostname"] == "localhost"
    assert result["process"] == "sshd"
    assert result["username"] == "faketestuser"
    assert result["source_ip"] == "::1"
    assert result["status"] == "failure"
    assert result["raw"] == line


def test_parse_auth_windows_invalid_user():
    line = "6376 2026-08-16 03:17:20.233 Invalid user faketestuser from ::1 port 51785"
    result = parse_auth_log_line(line)
    assert result is not None
    assert result["timestamp"] == "2026-08-16 03:17:20.233"
    assert result["hostname"] == "localhost"
    assert result["process"] == "sshd"
    assert result["username"] == "faketestuser"
    assert result["source_ip"] == "::1"
    assert result["status"] == "failure"
    assert result["raw"] == line


def test_parse_auth_windows_accepted_password():
    line = "6376 2026-08-16 03:20:11.400 Accepted password for realuser from 192.168.1.5 port 51790 ssh2"
    result = parse_auth_log_line(line)
    assert result is not None
    assert result["timestamp"] == "2026-08-16 03:20:11.400"
    assert result["hostname"] == "localhost"
    assert result["process"] == "sshd"
    assert result["username"] == "realuser"
    assert result["source_ip"] == "192.168.1.5"
    assert result["status"] == "success"


def test_parse_auth_windows_dict_shape_matches_linux():
    win = parse_auth_log_line(
        "6376 2026-08-16 03:17:28.251 Failed password for admin from ::1 port 51785 ssh2")
    lin = parse_auth_log_line(
        "May 27 09:10:01 server sshd[1001]: Failed password for admin from 192.168.1.100 port 22 ssh2")
    assert set(win.keys()) == set(lin.keys())


# --- parser: access ---

def test_parse_access_returns_none_on_blank():
    assert parse_access_log_line("") is None
    assert parse_access_log_line("garbage") is None


def test_parse_access_log_line():
    line = '10.0.0.50 - - [27/May/2026:10:00:01 +0000] "GET /admin HTTP/1.1" 403 512 "-" "Mozilla/5.0"'
    result = parse_access_log_line(line)
    assert result is not None
    assert result["source_ip"] == "10.0.0.50"
    assert result["resource"] == "/admin"
    assert result["status_code"] == "403"
    assert result["method"] == "GET"


# --- preprocessor ---

def test_auth_log_returns_enough_events():
    events = preprocess_log_file("logs/samples/auth.log", "auth")
    assert len(events) >= 15


def test_web_log_returns_enough_events():
    events = preprocess_log_file("logs/samples/access.log", "web")
    assert len(events) >= 15


def test_all_auth_events_have_schema_keys():
    events = preprocess_log_file("logs/samples/auth.log", "auth")
    for event in events:
        assert SCHEMA_KEYS.issubset(set(event.keys()))


def test_all_web_events_have_schema_keys():
    events = preprocess_log_file("logs/samples/access.log", "web")
    for event in events:
        assert SCHEMA_KEYS.issubset(set(event.keys()))


def test_timestamp_is_datetime_auth():
    events = preprocess_log_file("logs/samples/auth.log", "auth")
    for event in events:
        assert isinstance(event["timestamp"], datetime)


def test_timestamp_is_datetime_web():
    events = preprocess_log_file("logs/samples/access.log", "web")
    for event in events:
        assert isinstance(event["timestamp"], datetime)


def test_auth_failed_events_have_failed_status_code():
    events = preprocess_log_file("logs/samples/auth.log", "auth")
    failed = [e for e in events if e["status_code"] == "FAILED"]
    assert len(failed) > 0


def test_auth_success_events_have_success_status_code():
    events = preprocess_log_file("logs/samples/auth.log", "auth")
    success = [e for e in events if e["status_code"] == "SUCCESS"]
    assert len(success) > 0


def test_web_events_have_numeric_string_status_codes():
    events = preprocess_log_file("logs/samples/access.log", "web")
    for event in events:
        assert event["status_code"].isdigit()
