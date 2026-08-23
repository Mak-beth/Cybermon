from src.detection.matching import matches_restricted

# Kept so existing references to the old private name keep working; the single
# implementation now lives in src/detection/matching.py and is shared with the
# scoring layer.
_matches_restricted = matches_restricted


def detect_unauthorized_access(events: list[dict], config: dict) -> list[dict]:
    cfg = config["detection"]["unauthorized_access"]
    restricted = set(cfg["restricted_resources"])
    trigger_codes = {str(c) for c in cfg["trigger_codes"]}

    violations = []
    for event in events:
        if (str(event.get("status_code", "")) in trigger_codes
                and _matches_restricted(event.get("resource") or "", restricted)):
            violations.append({
                "violation_type": "unauthorized_access",
                "timestamp": event["timestamp"],
                "username": event.get("username"),
                "source_ip": event.get("source_ip"),
                "resource": event.get("resource"),
                "detail": (
                    f"HTTP {event['status_code']} on restricted resource "
                    f"'{event['resource']}' from {event.get('source_ip')}"
                ),
            })

    return violations
