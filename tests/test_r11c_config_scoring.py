"""R11-C tests — config-driven scoring rules.

All values that drive likelihood/impact now come from config["scoring"]["rules"]
with built-in fallbacks when the section is absent.
"""
import copy

from src.scoring.rules import get_likelihood, get_impact
from src.scoring.scorer import score_violation

_TIERS = {"severity_tiers": {
    "low": {"min": 1, "max": 4}, "medium": {"min": 5, "max": 9},
    "high": {"min": 10, "max": 16}, "critical": {"min": 17, "max": 25},
}}


def _cfg_with_rules(**rules) -> dict:
    return {"scoring": {**_TIERS, "rules": rules}}


def _failed(username: str, detail: str = "8 failed logins in 10 min") -> dict:
    return {
        "violation_type": "failed_logins",
        "username": username,
        "resource": None,
        "detail": detail,
    }


def _unauth(resource: str) -> dict:
    return {
        "violation_type": "unauthorized_access",
        "username": None,
        "resource": resource,
        "detail": f"HTTP 403 on restricted resource '{resource}'",
    }


def test_custom_high_impact_user_gets_correct_impact():
    config = _cfg_with_rules(
        high_impact_users=["superuser"],
        failed_login_high_user_impact=4,
    )
    v = _failed("superuser")
    assert get_impact(v, config) == 4


def test_default_admin_still_works_with_custom_config():
    config = _cfg_with_rules(
        high_impact_users=["superuser", "admin"],
        failed_login_high_user_impact=4,
    )
    assert get_impact(_failed("admin"), config) == 4
    assert get_impact(_failed("superuser"), config) == 4


def test_custom_high_resource_gets_correct_impact():
    config = _cfg_with_rules(
        high_impact_resources=["/secret"],
        unauthorized_access_high_resource_impact=5,
    )
    assert get_impact(_unauth("/secret"), config) == 5


def test_unconfigured_resource_gets_default_impact():
    config = _cfg_with_rules(
        high_impact_resources=["/admin"],
        med_impact_resources=["/config"],
        unauthorized_access_default_impact=2,
    )
    assert get_impact(_unauth("/someother"), config) == 2


def test_likelihood_band_from_config():
    config = _cfg_with_rules(
        failed_login_likelihood_bands=[
            {"max_count": 3, "likelihood": 2},
            {"max_count": 99999, "likelihood": 5},
        ],
    )
    v = _failed("bob", detail="3 failed logins in 10 min for user 'bob'")
    assert get_likelihood(v, config) == 2


def test_fallback_when_scoring_rules_absent():
    """No scoring.rules key — fallback defaults apply, no exception."""
    config = {"scoring": copy.deepcopy(_TIERS)}
    v = _failed("admin")
    likelihood = get_likelihood(v, config)
    impact = get_impact(v, config)
    assert isinstance(likelihood, int) and 1 <= likelihood <= 5
    assert isinstance(impact, int) and 1 <= impact <= 5
    assert impact == 4   # admin is in the fallback high-impact users


def test_score_changes_when_config_changes():
    """The same violation scores differently when config rules change."""
    v = _failed("svc-account")

    default_cfg = _cfg_with_rules(
        high_impact_users=["root", "admin"],
        failed_login_high_user_impact=4,
        failed_login_default_impact=2,
    )
    custom_cfg = _cfg_with_rules(
        high_impact_users=["root", "admin", "svc-account"],
        failed_login_high_user_impact=4,
        failed_login_default_impact=2,
    )

    default_score = score_violation(v, default_cfg)["risk_score"]
    custom_score = score_violation(v, custom_cfg)["risk_score"]
    assert default_score != custom_score
    assert custom_score > default_score
