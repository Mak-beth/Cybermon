"""Privilege-aware impact for off-hours logins.

Previously every off_hours_login scored exactly 6/Medium regardless of account,
so an out-of-hours root login ranked identically to a standard user's — the
"false priority" risk raised in supervision.

Impact now reuses the SAME high_impact_users list as failed_logins.
Likelihood is deliberately unchanged (frequency axis, per IR Table 3.2), and
no time-of-day banding is applied.
"""
import copy

import pytest
import yaml

from src.scoring.rules import get_impact, get_likelihood
from src.scoring.scorer import score_violation

_TIERS = {"severity_tiers": {
    "low": {"min": 1, "max": 4}, "medium": {"min": 5, "max": 9},
    "high": {"min": 10, "max": 16}, "critical": {"min": 17, "max": 25},
}}


@pytest.fixture
def shipped_config():
    """The real config.yaml — proves the shipped values produce these scores."""
    with open("config/config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _off_hours(username):
    return {
        "violation_type": "off_hours_login",
        "username": username,
        "resource": None,
        "detail": f"Successful login at 03:14 on Monday (outside business hours)",
    }


# ---------------------------------------------------------------------------
# Privileged accounts -> raised impact
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("username", ["admin", "root"])
def test_off_hours_privileged_user_scores_high(shipped_config, username):
    """admin/root off-hours -> impact 5, score 10, High."""
    v = _off_hours(username)
    assert get_impact(v, shipped_config) == 5
    scored = score_violation(v, shipped_config)
    assert scored["likelihood"] == 2          # unchanged
    assert scored["impact"] == 5
    assert scored["risk_score"] == 10
    assert scored["severity"] == "High"


# ---------------------------------------------------------------------------
# Standard accounts -> unchanged (regression guard)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("username", ["alice", "bjones", "svc_backup", None])
def test_off_hours_standard_user_unchanged(shipped_config, username):
    """Non-privileged off-hours -> impact 3, score 6, Medium: exactly as before."""
    v = _off_hours(username)
    assert get_impact(v, shipped_config) == 3
    scored = score_violation(v, shipped_config)
    assert scored["likelihood"] == 2
    assert scored["impact"] == 3
    assert scored["risk_score"] == 6
    assert scored["severity"] == "Medium"


def test_off_hours_likelihood_is_not_changed_by_privilege(shipped_config):
    """Likelihood stays on the frequency axis — privilege must not touch it."""
    assert get_likelihood(_off_hours("root"), shipped_config) == 2
    assert get_likelihood(_off_hours("alice"), shipped_config) == 2


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

def test_missing_off_hours_high_user_impact_falls_back_to_flat_behaviour():
    """An older config without the new key keeps the previous flat scoring."""
    config = {"scoring": {**_TIERS, "rules": {
        "high_impact_users": ["root", "admin"],
        "off_hours_default_likelihood": 2,
        "off_hours_default_impact": 3,
        # off_hours_high_user_impact deliberately absent
    }}}
    for username in ("root", "admin", "alice"):
        v = _off_hours(username)
        assert get_impact(v, config) == 3, f"{username} should fall back to 3"
        assert score_violation(v, config)["severity"] == "Medium"


def test_missing_scoring_rules_section_entirely_does_not_crash():
    """No scoring.rules at all -> built-in fallbacks, still a valid score."""
    config = {"scoring": copy.deepcopy(_TIERS)}
    scored = score_violation(_off_hours("root"), config)
    assert isinstance(scored["risk_score"], int)
    assert scored["severity"] in ("Low", "Medium", "High", "Critical")


def test_custom_high_impact_users_list_drives_off_hours_impact():
    """The privilege list is config-driven — same mechanism as failed_logins."""
    config = {"scoring": {**_TIERS, "rules": {
        "high_impact_users": ["superuser"],
        "off_hours_default_likelihood": 2,
        "off_hours_default_impact": 3,
        "off_hours_high_user_impact": 5,
    }}}
    assert get_impact(_off_hours("superuser"), config) == 5
    assert get_impact(_off_hours("root"), config) == 3   # not in the custom list


# ---------------------------------------------------------------------------
# Other violation types must be untouched
# ---------------------------------------------------------------------------

def test_other_violation_types_unaffected(shipped_config):
    """failed_logins and unauthorized_access scoring must not change."""
    failed_admin = {"violation_type": "failed_logins", "username": "admin",
                    "resource": None, "detail": "8 failed logins in 10 min"}
    assert get_impact(failed_admin, shipped_config) == 4     # not 5

    unauth = {"violation_type": "unauthorized_access", "username": None,
              "resource": "/admin", "detail": "HTTP 403"}
    assert get_impact(unauth, shipped_config) == 5
    assert score_violation(unauth, shipped_config)["risk_score"] == 15
