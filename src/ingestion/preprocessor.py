from datetime import datetime
from src.ingestion.reader import read_log_file
from src.ingestion.parser import parse_auth_log_line, parse_access_log_line


def _parse_auth_timestamp(ts_str: str) -> datetime:
    year = datetime.now().year
    normalized = " ".join(ts_str.strip().split())
    return datetime.strptime(f"{year} {normalized}", "%Y %b %d %H:%M:%S")


def _parse_access_timestamp(ts_str: str) -> datetime:
    ts_part = ts_str.split(" ")[0]
    return datetime.strptime(ts_part, "%d/%b/%Y:%H:%M:%S")


def normalize_event(parsed: dict, log_type: str) -> dict:
    if log_type == "auth":
        return {
            "timestamp": _parse_auth_timestamp(parsed["timestamp"]),
            "username": parsed.get("username"),
            "source_ip": parsed.get("source_ip"),
            "resource": None,
            "action": "ssh_login",
            "status_code": "SUCCESS" if parsed["status"] == "success" else "FAILED",
        }
    if log_type == "web":
        return {
            "timestamp": _parse_access_timestamp(parsed["timestamp"]),
            "username": None,
            "source_ip": parsed.get("source_ip"),
            "resource": parsed.get("resource"),
            "action": "http_request",
            "status_code": parsed.get("status_code", ""),
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
