import re
import socket
from datetime import datetime
from src.ingestion.reader import read_log_file
from src.ingestion.parser import parse_auth_log_line, parse_access_log_line

# Windows OpenSSH: "2026-08-16 03:17:28[.mmm]" — 4-digit year, hyphenated ISO date.
_WINDOWS_TS_RE = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
# Linux syslog: "Aug 16 03:17:28" — leading month abbreviation, no year.
_LINUX_TS_RE = re.compile(r'^[A-Za-z]{3} ')


def _parse_auth_timestamp(ts_str: str) -> datetime:
    normalized = " ".join(ts_str.strip().split())

    # Windows OpenSSH ISO timestamp already carries the full year — no inference.
    # Fractional seconds are optional (.251, .123456, or none).
    if _WINDOWS_TS_RE.match(normalized):
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(normalized, fmt)
            except ValueError:
                continue
        raise ValueError(f"Unrecognised Windows auth timestamp: {ts_str!r}")

    # Linux syslog timestamp (unchanged). Auth logs omit the year. Try current
    # year; if the result is in the future (log file pre-dates this run), fall
    # back to the previous year.
    if _LINUX_TS_RE.match(normalized):
        now = datetime.now()
        for year in (now.year, now.year - 1):
            dt = datetime.strptime(f"{year} {normalized}", "%Y %b %d %H:%M:%S")
            if dt <= now:
                return dt
        return dt

    raise ValueError(f"Unrecognised auth timestamp format: {ts_str!r}")


def _parse_access_timestamp(ts_str: str) -> datetime:
    ts_part = ts_str.split(" ")[0]
    return datetime.strptime(ts_part, "%d/%b/%Y:%H:%M:%S")


def normalize_event(parsed: dict, log_type: str) -> dict:
    host = socket.gethostname()
    if log_type == "auth":
        return {
            "timestamp": _parse_auth_timestamp(parsed["timestamp"]),
            "username": parsed.get("username"),
            "source_ip": parsed.get("source_ip"),
            "resource": None,
            "action": "ssh_login",
            "status_code": "SUCCESS" if parsed["status"] == "success" else "FAILED",
            "source_host": host,
            "raw_log": parsed.get("raw"),   # original log line from parser
        }
    if log_type == "web":
        return {
            "timestamp": _parse_access_timestamp(parsed["timestamp"]),
            "username": None,
            "source_ip": parsed.get("source_ip"),
            "resource": parsed.get("resource"),
            "action": "http_request",
            "status_code": parsed.get("status_code", ""),
            "source_host": host,
            "raw_log": parsed.get("raw"),   # original log line from parser
        }
    raise ValueError(f"Unknown log_type: {log_type}")


def preprocess_log_file(filepath: str, log_type: str) -> list[dict]:
    lines = read_log_file(filepath)
    parser = parse_auth_log_line if log_type == "auth" else parse_access_log_line
    events = []
    for line in lines:
        parsed = parser(line)
        if parsed is not None:
            events.append(normalize_event(parsed, log_type))
    return events
