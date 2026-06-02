"""GUI data access layer.

Provides read-only query functions for the PyQt6 GUI panels.
All functions connect directly to the SQLite database configured in
config/config.yaml.  They never modify data.
"""
import os
import sqlite3

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.abspath(os.path.join(_HERE, "..", ".."))

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
    config_path = os.path.join(_BASE_DIR, "config", "config.yaml")
    with open(config_path, encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    raw = config["storage"]["db_path"]
    return raw if os.path.isabs(raw) else os.path.join(_BASE_DIR, raw)


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
    """Return a single violation dict, or an empty dict if not found."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT v.id, v.violation_type, v.timestamp, v.username,
               v.source_ip, v.resource, v.detail, v.source_host,
               r.likelihood, r.impact, r.risk_score, r.severity
        FROM violations v
        JOIN risk_scores r ON r.violation_id = v.id
        WHERE v.id = ?
    """, (violation_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return {}
    d = dict(row)
    d["recommended_action"] = RECOMMENDED_ACTIONS.get(d["severity"], "")
    return d


def get_summary_counts() -> dict:
    """Return aggregate counts for the overview panel.

    Returns:
        {
            "total": int,
            "by_type": {"failed_logins": int, "unauthorized_access": int,
                         "off_hours_login": int},
            "by_severity": {"Low": int, "Medium": int,
                             "High": int, "Critical": int},
        }
    """
    conn = _connect()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM violations")
    total = cur.fetchone()[0]

    by_type = {"failed_logins": 0, "unauthorized_access": 0, "off_hours_login": 0}
    cur.execute(
        "SELECT violation_type, COUNT(*) FROM violations GROUP BY violation_type"
    )
    for vtype, count in cur.fetchall():
        by_type[vtype] = count

    by_severity = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0}
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
