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
