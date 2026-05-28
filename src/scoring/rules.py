import re

_HIGH_IMPACT_RESOURCES = {"/admin", "/.env", "/phpmyadmin"}
_MED_IMPACT_RESOURCES  = {"/config", "/wp-admin"}
_HIGH_IMPACT_USERS     = {"root", "admin"}

_COUNT_RE = re.compile(r"^(\d+)")


def _extract_count(detail: str) -> int:
    m = _COUNT_RE.match(detail)
    return int(m.group(1)) if m else 0


def get_likelihood(violation: dict) -> int:
    vtype = violation["violation_type"]

    if vtype == "failed_logins":
        count = _extract_count(violation.get("detail", ""))
        if count <= 5:
            return 2
        if count <= 9:
            return 3
        if count <= 19:
            return 4
        return 5

    if vtype == "unauthorized_access":
        return 3

    if vtype == "off_hours_login":
        return 2

    return 1


def get_impact(violation: dict) -> int:
    vtype = violation["violation_type"]

    if vtype == "failed_logins":
        return 4 if violation.get("username") in _HIGH_IMPACT_USERS else 2

    if vtype == "unauthorized_access":
        resource = violation.get("resource", "")
        if resource in _HIGH_IMPACT_RESOURCES:
            return 5
        if resource in _MED_IMPACT_RESOURCES:
            return 3
        return 2

    if vtype == "off_hours_login":
        return 3

    return 1
