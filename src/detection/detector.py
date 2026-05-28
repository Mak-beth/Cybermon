from src.detection.rules.failed_logins import detect_failed_logins
from src.detection.rules.unauthorized_access import detect_unauthorized_access
from src.detection.rules.off_hours import detect_off_hours_logins


def run_detection(events: list[dict], config: dict) -> list[dict]:
    violations = []
    violations.extend(detect_failed_logins(events, config))
    violations.extend(detect_unauthorized_access(events, config))
    violations.extend(detect_off_hours_logins(events, config))
    return violations
