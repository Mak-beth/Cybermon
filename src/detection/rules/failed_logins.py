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

    for username, group in df.groupby("username"):
        group = group.sort_values("timestamp").reset_index(drop=True)
        timestamps = group["timestamp"].tolist()
        window = pd.Timedelta(minutes=window_minutes)

        for i, t_start in enumerate(timestamps):
            count = sum(1 for t in timestamps[i:] if t - t_start <= window)
            if count > threshold:
                violations.append({
                    "violation_type": "failed_logins",
                    "timestamp": group.iloc[i]["timestamp"].to_pydatetime(),
                    "username": username,
                    "source_ip": group.iloc[i].get("source_ip"),
                    "resource": None,
                    "detail": f"{count} failed logins in {window_minutes} min for user '{username}'",
                })
                break

    return violations
