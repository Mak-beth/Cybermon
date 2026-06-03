"""GUI data access layer.

Provides read-only query functions for the PyQt6 GUI panels.
All functions connect directly to the SQLite database configured in
config/config.yaml.  They never modify data.
"""
import os
import sqlite3
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.abspath(os.path.join(_HERE, "..", ".."))
_db_path: str | None = None   # cached on first call to _get_db_path()


def _get_config_path() -> str:
    """Return the path to the writable config.yaml.

    In a PyInstaller onefile build this lives next to the .exe.
    In development it is in the project root.
    """
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(os.path.dirname(sys.executable), "config", "config.yaml")
    return os.path.join(_BASE_DIR, "config", "config.yaml")

# ---------------------------------------------------------------------------
# Recommended actions (mirrors dashboard RECOMMENDED_RESPONSE)
# ---------------------------------------------------------------------------
RECOMMENDED_ACTIONS: dict[str, str] = {
    "Low":      "Log and monitor. No immediate action required.",
    "Medium":   "Review and investigate at next available opportunity.",
    "High":     "Investigate promptly. Consider temporary account lock.",
    "Critical": "Immediate investigation and escalation required.",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_db_path() -> str:
    global _db_path
    if _db_path is None:
        with open(_get_config_path(), encoding="utf-8") as fh:
            config = yaml.safe_load(fh)
        raw = config["storage"]["db_path"]
        if os.path.isabs(raw):
            _db_path = raw
        elif hasattr(sys, "_MEIPASS"):
            # Resolve relative path next to the exe, not in the temp extraction dir
            _db_path = os.path.join(os.path.dirname(sys.executable), raw)
        else:
            _db_path = os.path.join(_BASE_DIR, raw)
    return _db_path


def _connect() -> sqlite3.Connection:
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_all_violations(host_filter: str | None = None) -> list[dict]:
    """Return all violations with scores, ordered by risk_score DESC.

    Args:
        host_filter: If provided, return only violations whose source_host
                     matches this value exactly.  None returns all hosts.

    Returns:
        List of dicts with keys:
            id, violation_type, timestamp, username, source_ip, resource,
            detail, source_host, likelihood, impact, risk_score, severity,
            recommended_action
    """
    conn = _connect()
    cur = conn.cursor()

    if host_filter and host_filter != "All Hosts":
        cur.execute("""
            SELECT v.id, v.violation_type, v.timestamp, v.username,
                   v.source_ip, v.resource, v.detail, v.source_host,
                   r.likelihood, r.impact, r.risk_score, r.severity
            FROM violations v
            JOIN risk_scores r ON r.violation_id = v.id
            WHERE v.source_host = ?
            ORDER BY r.risk_score DESC
        """, (host_filter,))
    else:
        cur.execute("""
            SELECT v.id, v.violation_type, v.timestamp, v.username,
                   v.source_ip, v.resource, v.detail, v.source_host,
                   r.likelihood, r.impact, r.risk_score, r.severity
            FROM violations v
            JOIN risk_scores r ON r.violation_id = v.id
            ORDER BY r.risk_score DESC
        """)

    rows = []
    for row in cur.fetchall():
        d = dict(row)
        d["recommended_action"] = RECOMMENDED_ACTIONS.get(d["severity"], "")
        rows.append(d)

    conn.close()
    return rows


def get_violation_by_id(violation_id: int) -> dict:
    """Return a single violation dict, or an empty dict if not found.

    LEFT JOINs to the events table via triggering_event_id to include raw_log.
    raw_log is None when triggering_event_id is NULL or the event was deleted.
    """
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT v.id, v.violation_type, v.timestamp, v.username,
               v.source_ip, v.resource, v.detail, v.source_host,
               v.triggering_event_id,
               r.likelihood, r.impact, r.risk_score, r.severity,
               e.raw_log
        FROM violations v
        JOIN risk_scores r ON r.violation_id = v.id
        LEFT JOIN events e ON e.id = v.triggering_event_id
        WHERE v.id = ?
    """, (violation_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return {}
    d = dict(row)
    d["recommended_action"] = RECOMMENDED_ACTIONS.get(d["severity"], "")
    return d


def get_new_violations_since(last_id: int) -> list[dict]:
    """Return violations with id > last_id, ordered by id ASC.

    Used by LiveFeedPanel to poll for new violations without duplicates.
    Returns lightweight dicts (no raw_log — the detail panel fetches that on demand).
    """
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT v.id, v.violation_type, v.timestamp,
               v.source_ip, v.source_host,
               r.risk_score, r.severity
        FROM violations v
        JOIN risk_scores r ON r.violation_id = v.id
        WHERE v.id > ?
        ORDER BY v.id ASC
    """, (last_id,))
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def get_summary_counts(host_filter: str | None = None) -> dict:
    """Return aggregate counts for the overview panel.

    Args:
        host_filter: If provided (and not "All Hosts"), restrict counts to
                     violations whose source_host matches exactly.

    Returns:
        {
            "total": int,
            "by_type": {"failed_logins": int, "unauthorized_access": int,
                         "off_hours_login": int},
            "by_severity": {"Low": int, "Medium": int,
                             "High": int, "Critical": int},
        }
    """
    filtered = bool(host_filter and host_filter != "All Hosts")
    conn = _connect()
    cur = conn.cursor()

    if filtered:
        cur.execute(
            "SELECT COUNT(*) FROM violations WHERE source_host = ?",
            (host_filter,),
        )
    else:
        cur.execute("SELECT COUNT(*) FROM violations")
    total = cur.fetchone()[0]

    by_type = {"failed_logins": 0, "unauthorized_access": 0, "off_hours_login": 0}
    if filtered:
        cur.execute(
            "SELECT violation_type, COUNT(*) FROM violations "
            "WHERE source_host = ? GROUP BY violation_type",
            (host_filter,),
        )
    else:
        cur.execute(
            "SELECT violation_type, COUNT(*) FROM violations GROUP BY violation_type"
        )
    for vtype, count in cur.fetchall():
        by_type[vtype] = count

    by_severity = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0}
    if filtered:
        # risk_scores.source_host is populated in R1 — no JOIN needed
        cur.execute(
            "SELECT severity, COUNT(*) FROM risk_scores "
            "WHERE source_host = ? GROUP BY severity",
            (host_filter,),
        )
    else:
        cur.execute(
            "SELECT severity, COUNT(*) FROM risk_scores GROUP BY severity"
        )
    for severity, count in cur.fetchall():
        by_severity[severity] = count

    conn.close()
    return {"total": total, "by_type": by_type, "by_severity": by_severity}


def get_unique_hosts() -> list[str]:
    """Return a sorted list of unique source_host values from violations."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT source_host FROM violations ORDER BY source_host"
    )
    hosts = [row[0] for row in cur.fetchall()]
    conn.close()
    return hosts


def get_trend_by_hour_today(host_filter: str | None = None) -> dict:
    """Return violation counts grouped by hour for today.

    Returns:
        {
            "hours": ["00", "01", ..., "23"],
            "failed_logins":       [int * 24],
            "unauthorized_access": [int * 24],
            "off_hours_login":     [int * 24],
        }
    """
    filtered = bool(host_filter and host_filter != "All Hosts")
    conn = _connect()
    cur = conn.cursor()

    if filtered:
        cur.execute("""
            SELECT strftime('%H', timestamp) AS hour,
                   violation_type,
                   COUNT(*) AS cnt
            FROM violations
            WHERE DATE(timestamp) = DATE('now')
              AND source_host = ?
            GROUP BY hour, violation_type
        """, (host_filter,))
    else:
        cur.execute("""
            SELECT strftime('%H', timestamp) AS hour,
                   violation_type,
                   COUNT(*) AS cnt
            FROM violations
            WHERE DATE(timestamp) = DATE('now')
            GROUP BY hour, violation_type
        """)

    rows = cur.fetchall()
    conn.close()

    result: dict = {
        "hours":              [f"{h:02d}" for h in range(24)],
        "failed_logins":       [0] * 24,
        "unauthorized_access": [0] * 24,
        "off_hours_login":     [0] * 24,
    }
    for row in rows:
        idx = int(row["hour"])
        vtype = row["violation_type"]
        if vtype in result:
            result[vtype][idx] = row["cnt"]
    return result


def get_max_violation_id() -> int:
    """Return the highest violation id in the database, or 0 if empty."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT MAX(id) FROM violations")
    result = cur.fetchone()[0]
    conn.close()
    return result if result is not None else 0


def get_violations_for_export(host_filter: str | None = None) -> list[dict]:
    """Return violations with log_excerpt for CSV export.

    Includes a LEFT JOIN to events for raw_log so the exported CSV has the
    log line that triggered each violation.  Respects host_filter identically
    to get_all_violations().
    """
    conn = _connect()
    cur = conn.cursor()

    if host_filter and host_filter != "All Hosts":
        cur.execute("""
            SELECT v.timestamp, v.violation_type, v.source_host,
                   r.likelihood, r.impact, r.risk_score, r.severity,
                   e.raw_log
            FROM violations v
            JOIN risk_scores r ON r.violation_id = v.id
            LEFT JOIN events e ON e.id = v.triggering_event_id
            WHERE v.source_host = ?
            ORDER BY r.risk_score DESC
        """, (host_filter,))
    else:
        cur.execute("""
            SELECT v.timestamp, v.violation_type, v.source_host,
                   r.likelihood, r.impact, r.risk_score, r.severity,
                   e.raw_log
            FROM violations v
            JOIN risk_scores r ON r.violation_id = v.id
            LEFT JOIN events e ON e.id = v.triggering_event_id
            ORDER BY r.risk_score DESC
        """)

    rows = []
    for row in cur.fetchall():
        d = dict(row)
        d["recommended_action"] = RECOMMENDED_ACTIONS.get(d["severity"], "")
        d["log_excerpt"] = d.pop("raw_log") or ""
        rows.append(d)

    conn.close()
    return rows


def get_trend_by_day_week(host_filter: str | None = None) -> dict:
    """Return violation counts grouped by date for the last 7 days.

    Always returns exactly 7 dates (6 days ago through today) so the chart
    has a predictable x-axis even on quiet days.

    Returns:
        {
            "dates": ["YYYY-MM-DD", ...],   # 7 entries
            "failed_logins":       [int * 7],
            "unauthorized_access": [int * 7],
            "off_hours_login":     [int * 7],
        }
    """
    from datetime import date, timedelta

    filtered = bool(host_filter and host_filter != "All Hosts")
    conn = _connect()
    cur = conn.cursor()

    if filtered:
        cur.execute("""
            SELECT DATE(timestamp) AS day,
                   violation_type,
                   COUNT(*) AS cnt
            FROM violations
            WHERE DATE(timestamp) >= DATE('now', '-6 days')
              AND source_host = ?
            GROUP BY day, violation_type
        """, (host_filter,))
    else:
        cur.execute("""
            SELECT DATE(timestamp) AS day,
                   violation_type,
                   COUNT(*) AS cnt
            FROM violations
            WHERE DATE(timestamp) >= DATE('now', '-6 days')
            GROUP BY day, violation_type
        """)

    rows = cur.fetchall()
    conn.close()

    today = date.today()
    dates = [(today - timedelta(days=6 - i)).isoformat() for i in range(7)]
    date_idx = {d: i for i, d in enumerate(dates)}

    result: dict = {
        "dates":              dates,
        "failed_logins":       [0] * 7,
        "unauthorized_access": [0] * 7,
        "off_hours_login":     [0] * 7,
    }
    for row in rows:
        day = row["day"]
        vtype = row["violation_type"]
        if day in date_idx and vtype in result:
            result[vtype][date_idx[day]] = row["cnt"]
    return result
