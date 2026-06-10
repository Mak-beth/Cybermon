def _matches_restricted(resource: str, restricted: set) -> bool:
    """Return True if resource starts with any restricted prefix.

    Prefix match (not substring): /admin matches /admin, /admin/, and
    /admin/login.php, but /administrator does not.  Query strings are
    stripped before matching so /admin?page=1 is caught too.
    """
    path = resource.split("?")[0]
    path = path.rstrip("/") or "/"
    for prefix in restricted:
        clean_prefix = prefix.rstrip("/")
        if path == clean_prefix or path.startswith(clean_prefix + "/"):
            return True
    return False


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
