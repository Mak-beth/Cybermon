import socket
import sqlite3

_ACTION_TO_LOG_TYPE = {"ssh_login": "auth", "http_request": "web"}


def _ts(value) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def insert_events(events: list[dict], db_path: str) -> None:
    _default_host = socket.gethostname()
    rows = [
        (
            _ts(e["timestamp"]),
            e.get("username"),
            e.get("source_ip"),
            e.get("resource"),
            e.get("action"),
            e.get("status_code"),
            _ACTION_TO_LOG_TYPE.get(e.get("action", ""), None),
            e.get("source_host", _default_host),
        )
        for e in events
    ]
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO events "
        "(timestamp, username, source_ip, resource, action, status_code, log_type, source_host) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def insert_violation(violation: dict, db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO violations "
        "(violation_type, timestamp, username, source_ip, resource, detail, source_host) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            violation["violation_type"],
            _ts(violation["timestamp"]),
            violation.get("username"),
            violation.get("source_ip"),
            violation.get("resource"),
            violation.get("detail"),
            violation.get("source_host", socket.gethostname()),
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def insert_risk_score(violation_id: int, scored: dict, db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO risk_scores "
        "(violation_id, likelihood, impact, risk_score, severity, source_host) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            violation_id,
            scored["likelihood"],
            scored["impact"],
            scored["risk_score"],
            scored["severity"],
            scored.get("source_host", socket.gethostname()),
        ),
    )
    conn.commit()
    conn.close()
