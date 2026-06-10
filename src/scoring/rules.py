"""Likelihood and impact rules — all values configurable via scoring.rules.

Every constant that drives scoring lives in config.yaml under scoring.rules
(R11-C).  When that section is absent (older config files), the built-in
fallback defaults below are used and a one-time warning is printed to stderr.
"""
import re
import sys

# Fallback defaults — used ONLY when scoring.rules is absent from config.
_FALLBACK_HIGH_USERS     = {"root", "admin"}
_FALLBACK_HIGH_RESOURCES = {"/admin", "/.env", "/phpmyadmin"}
_FALLBACK_MED_RESOURCES  = {"/config", "/wp-admin"}
_FALLBACK_BANDS = [
    {"max_count": 5,     "likelihood": 2},
    {"max_count": 9,     "likelihood": 3},
    {"max_count": 19,    "likelihood": 4},
    {"max_count": 99999, "likelihood": 5},
]

_COUNT_RE = re.compile(r"^(\d+)")

_warned_missing_rules = False


def _extract_count(detail: str) -> int:
    m = _COUNT_RE.match(detail)
    return int(m.group(1)) if m else 0


def _rules(config: dict) -> dict:
    """Return scoring.rules from config, or {} with a one-time warning."""
    global _warned_missing_rules
    rules = (config or {}).get("scoring", {}).get("rules")
    if rules is None:
        if not _warned_missing_rules:
            print(
                "[CyberMon] WARNING: scoring.rules not found in config — "
                "using built-in defaults",
                file=sys.stderr,
            )
            _warned_missing_rules = True
        return {}
    return rules


def get_likelihood(violation: dict, config: dict) -> int:
    rules = _rules(config)
    vtype = violation["violation_type"]

    if vtype == "failed_logins":
        count = _extract_count(violation.get("detail", ""))
        bands = rules.get("failed_login_likelihood_bands", _FALLBACK_BANDS)
        # Evaluated in order; first matching band wins.
        for band in bands:
            if count <= band["max_count"]:
                return band["likelihood"]
        return 5

    if vtype == "unauthorized_access":
        return rules.get("unauthorized_access_default_likelihood", 3)

    if vtype == "off_hours_login":
        return rules.get("off_hours_default_likelihood", 2)

    return 1


def get_impact(violation: dict, config: dict) -> int:
    rules = _rules(config)
    vtype = violation["violation_type"]

    if vtype == "failed_logins":
        high_users = set(rules.get("high_impact_users", _FALLBACK_HIGH_USERS))
        if violation.get("username") in high_users:
            return rules.get("failed_login_high_user_impact", 4)
        return rules.get("failed_login_default_impact", 2)

    if vtype == "unauthorized_access":
        resource = violation.get("resource") or ""
        high = set(rules.get("high_impact_resources", _FALLBACK_HIGH_RESOURCES))
        med  = set(rules.get("med_impact_resources", _FALLBACK_MED_RESOURCES))
        if resource in high:
            return rules.get("unauthorized_access_high_resource_impact", 5)
        if resource in med:
            return rules.get("unauthorized_access_med_resource_impact", 3)
        return rules.get("unauthorized_access_default_impact", 2)

    if vtype == "off_hours_login":
        return rules.get("off_hours_default_impact", 3)

    return 1
