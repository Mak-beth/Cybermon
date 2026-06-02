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
            e.get("raw_log"),          # None → SQL NULL when key absent
        )
        for e in events
    ]
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO events "
        "(timestamp, username, source_ip, resource, action, status_code, "
        " log_type, source_host, raw_log) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def find_triggering_event_id(violation: dict, db_path: str) -> int | None:
    """Return the MAX(id) of the event most likely to have triggered this violation.

    Uses the violation's key fields to query the events table.  Returns None when
    no matching event is found; insert_violation() will store NULL in that case.

    Lives here (alongside insert_violation) so both main.py and
    server/ingest_endpoint.py can import it from a single module.
    """
    vtype      = violation.get("violation_type", "")
    username   = violation.get("username")
    source_ip  = violation.get("source_ip")
    resource   = violation.get("resource")
    source_host = violation.get("source_host", socket.gethostname())

    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()
    try:
        if vtype == "failed_logins":
            cur.execute(
                "SELECT MAX(id) FROM events "
                "WHERE username = ? AND source_ip = ? "
                "  AND status_code = 'FAILED' AND source_host = ?",
                (username, source_ip, source_host),
            )
        elif vtype == "unauthorized_access":
            cur.execute(
                "SELECT MAX(id) FROM events "
                "WHERE source_ip = ? AND resource = ? "
                "  AND status_code IN ('401', '403') AND source_host = ?",
                (source_ip, resource, source_host),
            )
        elif vtype == "off_hours_login":
            cur.execute(
                "SELECT MAX(id) FROM events "
                "WHERE username = ? AND source_ip = ? "
                "  AND status_code = 'SUCCESS' AND source_host = ?",
                (username, source_ip, source_host),
            )
        else:
            return None
        row = cur.fetchone()
        return row[0] if (row and row[0] is not None) else None
    finally:
        conn.close()


def insert_violation(violation: dict, db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO violations "
        "(violation_type, timestamp, username, source_ip, resource, detail, "
        " source_host, triggering_event_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            violation["violation_type"],
            _ts(violation["timestamp"]),
            violation.get("username"),
            violation.get("source_ip"),
            violation.get("resource"),
            violation.get("detail"),
            violation.get("source_host", socket.gethostname()),
            violation.get("triggering_event_id"),   # None → SQL NULL when absent
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
