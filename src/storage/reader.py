import sqlite3
from datetime import date, timedelta


def get_all_violations_with_scores(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT v.id, v.violation_type, v.timestamp, v.username, v.source_ip,
               v.resource, v.detail, v.source_host,
               r.likelihood, r.impact, r.risk_score, r.severity
        FROM violations v
        JOIN risk_scores r ON r.violation_id = v.id
        ORDER BY r.risk_score DESC
    """)
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def get_summary_counts(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM violations")
    total = cur.fetchone()[0]

    by_type = {"failed_logins": 0, "unauthorized_access": 0, "off_hours_login": 0}
    cur.execute("SELECT violation_type, COUNT(*) FROM violations GROUP BY violation_type")
    for vtype, count in cur.fetchall():
        by_type[vtype] = count

    by_severity = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0}
    cur.execute("SELECT severity, COUNT(*) FROM risk_scores GROUP BY severity")
    for severity, count in cur.fetchall():
        by_severity[severity] = count

    conn.close()
    return {"total": total, "by_type": by_type, "by_severity": by_severity}


def get_violation_detail(violation_id: int, db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT v.id, v.violation_type, v.timestamp, v.username, v.source_ip,
               v.resource, v.detail, v.source_host,
               r.likelihood, r.impact, r.risk_score, r.severity
        FROM violations v
        JOIN risk_scores r ON r.violation_id = v.id
        WHERE v.id = ?
    """, (violation_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else {}


def get_trend_by_hour_today(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT strftime('%H', timestamp) AS hour,
               violation_type,
               COUNT(*) AS count
        FROM violations
        WHERE DATE(timestamp) = DATE('now')
        GROUP BY hour, violation_type
    """)
    rows = cur.fetchall()
    conn.close()

    result = {
        "hours": [f"{h:02d}" for h in range(24)],
        "failed_logins":       [0] * 24,
        "unauthorized_access": [0] * 24,
        "off_hours_login":     [0] * 24,
    }
    for hour_str, vtype, count in rows:
        idx = int(hour_str)
        if vtype in result:
            result[vtype][idx] = count
    return result


def get_trend_by_day_week(db_path: str) -> dict:
    """Return violation counts grouped by date and type for the past 7 days.

    The returned dict always has exactly 7 date entries (6 days ago through
    today) so the chart has a fixed, predictable x-axis even on quiet days.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT DATE(timestamp) AS day,
               violation_type,
               COUNT(*) AS count
        FROM violations
        WHERE DATE(timestamp) >= DATE('now', '-6 days')
        GROUP BY day, violation_type
    """)
    rows = cur.fetchall()
    conn.close()

    today = date.today()
    dates = [(today - timedelta(days=6 - i)).isoformat() for i in range(7)]
    date_idx = {d: i for i, d in enumerate(dates)}

    result = {
        "dates":              dates,
        "failed_logins":       [0] * 7,
        "unauthorized_access": [0] * 7,
        "off_hours_login":     [0] * 7,
    }
    for day_str, vtype, count in rows:
        if day_str in date_idx and vtype in result:
            result[vtype][date_idx[day_str]] = count
    return result


def get_trend_data(db_path: str, days: int = 365) -> list[dict]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT DATE(timestamp) as date, COUNT(*) as count
        FROM violations
        WHERE timestamp >= DATE('now', ?)
        GROUP BY DATE(timestamp)
        ORDER BY date
    """, (f"-{days} days",))
    rows = [{"date": row[0], "count": row[1]} for row in cur.fetchall()]
    conn.close()
    return rows
