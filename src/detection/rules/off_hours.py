from datetime import time


def detect_off_hours_logins(events: list[dict], config: dict) -> list[dict]:
    cfg = config["detection"]["off_hours_logins"]
    business_days = set(cfg["business_days"])
    start_h, start_m = map(int, cfg["business_hours_start"].split(":"))
    end_h, end_m = map(int, cfg["business_hours_end"].split(":"))
    business_start = time(start_h, start_m)
    business_end = time(end_h, end_m)

    violations = []
    for event in events:
        if event.get("status_code") != "SUCCESS":
            continue
        ts = event["timestamp"]
        is_business_day = ts.weekday() in business_days
        is_business_hours = business_start <= ts.time() < business_end

        if not (is_business_day and is_business_hours):
            violations.append({
                "violation_type": "off_hours_login",
                "timestamp": ts,
                "username": event.get("username"),
                "source_ip": event.get("source_ip"),
                "resource": None,
                "detail": (
                    f"Successful login at {ts.strftime('%H:%M')} on "
                    f"{ts.strftime('%A')} (outside business hours)"
                ),
            })

    return violations
