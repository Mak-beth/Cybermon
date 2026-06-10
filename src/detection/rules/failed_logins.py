import sqlite3
from datetime import datetime, timedelta

import pandas as pd


def detect_failed_logins(events: list[dict], config: dict) -> list[dict]:
    cfg = config["detection"]["failed_logins"]
    threshold = cfg["threshold"]
    window_minutes = cfg["time_window_minutes"]

    failed = [e for e in events if e.get("status_code") == "FAILED"]
    if not failed:
        return []

    df = pd.DataFrame(failed)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")

    violations = []
    window = pd.Timedelta(minutes=window_minutes)

    for username, group in df.groupby("username"):
        group = group.sort_values("timestamp").reset_index(drop=True)
        timestamps = group["timestamp"].tolist()

        # Track the maximum window count rather than stopping at the first
        # trigger — this ensures the detail reflects the worst burst and the
        # scorer assigns the correct likelihood (e.g. 20 failures → Critical).
        left = 0
        max_count = 0
        max_left = 0
        for right in range(len(timestamps)):
            while timestamps[right] - timestamps[left] > window:
                left += 1
            count = right - left + 1
            if count > max_count:
                max_count = count
                max_left = left

        if max_count > threshold:
            violations.append({
                "violation_type": "failed_logins",
                "timestamp": timestamps[max_left].to_pydatetime(),
                "username": username,
                "source_ip": group.iloc[max_left].get("source_ip"),
                "resource": None,
                "detail": f"{max_count} failed logins in {window_minutes} min for user '{username}'",
            })

    return violations


def detect_failed_logins_from_db(
    events: list[dict],
    config: dict,
    db_path: str,
    source_host: str,
) -> list[dict]:
    """Stateful failed-login detection for network mode.

    Instead of scanning only the current batch, this function:
    1. Identifies unique (username, source_host) pairs in the incoming events
    2. Queries the database for ALL failed-login events for those pairs
       within the configured time window (the caller inserts the batch into
       the events table BEFORE calling this, so the count covers DB + batch)
    3. Runs the threshold check against that combined count
    4. Returns violations only for pairs that reach the threshold

    This ensures that a slow brute force spread across many small batches
    is detected correctly — the batch-only approach misses it entirely.

    Raw sqlite3 is used deliberately: importing from src.storage here would
    create a circular import between detection and storage.
    """
    cfg = config["detection"]["failed_logins"]
    threshold = cfg["threshold"]
    window_minutes = cfg["time_window_minutes"]
    cutoff = (datetime.now() - timedelta(minutes=window_minutes)).isoformat()

    # Unique (username, host) pairs among FAILED events in this batch.
    # Keep the last event per pair so the violation carries a source_ip.
    pairs: dict[tuple, dict] = {}
    for e in events:
        if e.get("status_code") == "FAILED" and e.get("username"):
            host = e.get("source_host") or source_host
            pairs[(e["username"], host)] = e

    if not pairs:
        return []

    violations = []
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        for (username, host), last_event in pairs.items():
            cur.execute(
                "SELECT timestamp FROM events "
                "WHERE username = ? "
                "  AND source_host = ? "
                "  AND status_code = 'FAILED' "
                "  AND timestamp >= ? "
                "ORDER BY timestamp ASC",
                (username, host, cutoff),
            )
            rows = cur.fetchall()
            count = len(rows)
            if count < threshold:
                continue

            # Dedup: if this pair already has a violation recorded within the
            # window, the burst has been reported — do not emit another.
            cur.execute(
                "SELECT COUNT(*) FROM violations "
                "WHERE violation_type = 'failed_logins' "
                "  AND username = ? "
                "  AND source_host = ? "
                "  AND timestamp >= ?",
                (username, host, cutoff),
            )
            if cur.fetchone()[0] > 0:
                continue

            first_ts = rows[0][0]
            try:
                ts = datetime.fromisoformat(first_ts)
            except (ValueError, TypeError):
                ts = datetime.now()

            violations.append({
                "violation_type": "failed_logins",
                "timestamp": ts,
                "username": username,
                "source_ip": last_event.get("source_ip"),
                "resource": None,
                "detail": (
                    f"{count} failed logins in "
                    f"{window_minutes} min for user '{username}'"
                ),
                "source_host": host,
            })
    finally:
        conn.close()

    return violations
