import copy
import pytest
import yaml
from datetime import datetime

from src.scoring.rules import get_likelihood, get_impact
from src.scoring.scorer import (
    calculate_score, assign_severity,
    score_violation, score_all_violations,
)

# Minimal config for direct rule calls - no scoring.rules key, so the
# built-in fallback defaults apply (R11-C).
_MIN_CONFIG = {"scoring": {"severity_tiers": {
    "low": {"min": 1, "max": 4}, "medium": {"min": 5, "max": 9},
    "high": {"min": 10, "max": 16}, "critical": {"min": 17, "max": 25},
}}}


@pytest.fixture
def config():
    with open("config/config.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture
def v_failed_admin():
    return {
        "violation_type": "failed_logins",
        "timestamp": datetime(2026, 5, 27, 9, 10, 1),
        "username": "admin",
        "source_ip": "192.168.1.100",
        "resource": None,
        "detail": "8 failed logins in 10 min for user 'admin'",
    }


@pytest.fixture
def v_failed_testuser():
    return {
        "violation_type": "failed_logins",
        "timestamp": datetime(2026, 5, 27, 8, 5, 22),
        "username": "testuser",
        "source_ip": "10.0.0.20",
        "resource": None,
        "detail": "3 failed logins in 10 min for user 'testuser'",
    }


@pytest.fixture
def v_unauth_admin():
    return {
        "violation_type": "unauthorized_access",
        "timestamp": datetime(2026, 5, 27, 10, 0, 1),
        "username": None,
        "source_ip": "10.0.0.50",
        "resource": "/admin",
        "detail": "HTTP 403 on restricted resource '/admin' from 10.0.0.50",
    }


@pytest.fixture
def v_unauth_config():
    return {
        "violation_type": "unauthorized_access",
        "timestamp": datetime(2026, 5, 27, 10, 10, 1),
        "username": None,
        "source_ip": "10.0.0.51",
        "resource": "/config",
        "detail": "HTTP 401 on restricted resource '/config' from 10.0.0.51",
    }


@pytest.fixture
def v_unauth_env():
    return {
        "violation_type": "unauthorized_access",
        "timestamp": datetime(2026, 5, 27, 14, 5, 0),
        "username": None,
        "source_ip": "10.0.0.53",
        "resource": "/.env",
        "detail": "HTTP 403 on restricted resource '/.env' from 10.0.0.53",
    }


@pytest.fixture
def v_off_hours():
    return {
        "violation_type": "off_hours_login",
        "timestamp": datetime(2026, 5, 27, 2, 14, 30),
        "username": "alice",
        "source_ip": "172.16.0.10",
        "resource": None,
        "detail": "Successful login at 02:14 on Wednesday (outside business hours)",
    }


# --- likelihood ---

def test_likelihood_failed_logins_count_3(v_failed_testuser):
    assert get_likelihood(v_failed_testuser, _MIN_CONFIG) == 2


def test_likelihood_failed_logins_count_8(v_failed_admin):
    assert get_likelihood(v_failed_admin, _MIN_CONFIG) == 3


def test_likelihood_unauthorized_access(v_unauth_admin):
    assert get_likelihood(v_unauth_admin, _MIN_CONFIG) == 3


def test_likelihood_off_hours(v_off_hours):
    assert get_likelihood(v_off_hours, _MIN_CONFIG) == 2


# --- impact ---

def test_impact_failed_logins_admin(v_failed_admin):
    assert get_impact(v_failed_admin, _MIN_CONFIG) == 4


def test_impact_failed_logins_standard_user(v_failed_testuser):
    assert get_impact(v_failed_testuser, _MIN_CONFIG) == 2


def test_impact_unauth_admin_resource(v_unauth_admin):
    assert get_impact(v_unauth_admin, _MIN_CONFIG) == 5


def test_impact_unauth_config_resource(v_unauth_config):
    assert get_impact(v_unauth_config, _MIN_CONFIG) == 3


def test_impact_unauth_env_resource(v_unauth_env):
    assert get_impact(v_unauth_env, _MIN_CONFIG) == 5


def test_impact_off_hours(v_off_hours):
    assert get_impact(v_off_hours, _MIN_CONFIG) == 3


# --- calculate_score ---

def test_calculate_score_multiply():
    assert calculate_score(3, 4) == 12
    assert calculate_score(2, 3) == 6
    assert calculate_score(5, 5) == 25
    assert calculate_score(1, 1) == 1


# --- assign_severity tier boundaries ---

@pytest.mark.parametrize("score,expected", [
    (1,  "Low"),
    (4,  "Low"),
    (5,  "Medium"),
    (9,  "Medium"),
    (10, "High"),
    (16, "High"),
    (17, "Critical"),
    (25, "Critical"),
])
def test_assign_severity_boundaries(config, score, expected):
    assert assign_severity(score, config) == expected


# --- score_violation ---

def test_score_violation_has_enriched_keys(config, v_failed_admin):
    scored = score_violation(v_failed_admin, config)
    for key in ("likelihood", "impact", "risk_score", "severity"):
        assert key in scored


def test_score_violation_risk_score_equals_product(config, v_failed_admin):
    scored = score_violation(v_failed_admin, config)
    assert scored["risk_score"] == scored["likelihood"] * scored["impact"]


def test_score_violation_preserves_original_keys(config, v_failed_admin):
    scored = score_violation(v_failed_admin, config)
    for key in v_failed_admin:
        assert key in scored


def test_score_violation_does_not_mutate_input(config, v_failed_admin):
    original = copy.deepcopy(v_failed_admin)
    score_violation(v_failed_admin, config)
    assert v_failed_admin == original


def test_score_violation_admin_failed_logins_is_high(config, v_failed_admin):
    scored = score_violation(v_failed_admin, config)
    assert scored["risk_score"] == 12
    assert scored["severity"] == "High"


def test_score_violation_unauth_admin_is_high(config, v_unauth_admin):
    scored = score_violation(v_unauth_admin, config)
    assert scored["risk_score"] == 15
    assert scored["severity"] == "High"


def test_score_violation_off_hours_is_medium(config, v_off_hours):
    scored = score_violation(v_off_hours, config)
    assert scored["risk_score"] == 6
    assert scored["severity"] == "Medium"


# --- score_all_violations ---

def test_score_all_violations_length(config, v_failed_admin, v_unauth_admin, v_off_hours):
    violations = [v_failed_admin, v_unauth_admin, v_off_hours]
    scored = score_all_violations(violations, config)
    assert len(scored) == 3


def test_score_all_violations_all_have_severity(config, v_failed_admin, v_unauth_admin, v_off_hours):
    scored = score_all_violations([v_failed_admin, v_unauth_admin, v_off_hours], config)
    assert all("severity" in v for v in scored)


def test_score_all_violations_product_holds(config, v_failed_admin, v_unauth_admin, v_off_hours):
    scored = score_all_violations([v_failed_admin, v_unauth_admin, v_off_hours], config)
    assert all(v["risk_score"] == v["likelihood"] * v["impact"] for v in scored)


def test_score_all_empty(config):
    assert score_all_violations([], config) == []


# --- full pipeline integration ---

def test_full_pipeline_scoring(config):
    from src.ingestion.preprocessor import preprocess_log_file
    from src.detection.detector import run_detection

    events = (preprocess_log_file("logs/samples/auth.log", "auth") +
              preprocess_log_file("logs/samples/access.log", "web"))
    violations = run_detection(events, config)
    scored = score_all_violations(violations, config)

    assert len(scored) == len(violations)
    assert all(v["risk_score"] == v["likelihood"] * v["impact"] for v in scored)
    assert all(v["severity"] in ("Low", "Medium", "High", "Critical") for v in scored)


# --- R12-A: scoring must use the same restricted matcher as detection ---
# Detection matched restricted resources by prefix while scoring matched by
# exact membership, so /admin scored High (15) but /admin/login.php scored
# Medium (6) — the same violation, two tiers apart.

def _unauth(resource):
    return {
        "violation_type": "unauthorized_access",
        "username": None,
        "resource": resource,
        "detail": f"HTTP 403 on restricted resource '{resource}'",
    }


def test_scoring_restricted_subpath_gets_restricted_impact(config):
    """/admin/login.php must score identically to /admin."""
    base = score_violation(_unauth("/admin"), config)
    sub = score_violation(_unauth("/admin/login.php"), config)
    assert sub["impact"] == base["impact"]
    assert sub["risk_score"] == base["risk_score"]
    assert sub["severity"] == base["severity"]


def test_scoring_restricted_with_query_string_gets_restricted_impact(config):
    """/admin?page=1 must score identically to /admin."""
    base = score_violation(_unauth("/admin"), config)
    query = score_violation(_unauth("/admin?page=1"), config)
    assert query["impact"] == base["impact"]
    assert query["risk_score"] == base["risk_score"]
    assert query["severity"] == base["severity"]


def test_scoring_exact_restricted_still_correct(config):
    """Regression guard: /admin is unchanged from previous behaviour."""
    scored = score_violation(_unauth("/admin"), config)
    assert scored["impact"] == 5
    assert scored["risk_score"] == 15
    assert scored["severity"] == "High"


def test_scoring_prefix_collision_not_treated_as_restricted(config):
    """/administrator shares a prefix with /admin but is a different path."""
    scored = score_violation(_unauth("/administrator"), config)
    assert scored["impact"] == 2
    assert scored["severity"] != "High"


def test_detection_and_scoring_agree_on_restricted_paths(config):
    """The two layers must return the same verdict for every path.

    This is the test that would have caught the original defect.
    """
    from datetime import datetime
    from src.detection.rules.unauthorized_access import detect_unauthorized_access

    restricted = set(config["detection"]["unauthorized_access"]["restricted_resources"])
    high = set(config["scoring"]["rules"]["high_impact_resources"])
    med = set(config["scoring"]["rules"]["med_impact_resources"])
    default_impact = config["scoring"]["rules"]["unauthorized_access_default_impact"]

    verdicts = []
    for resource in ["/admin", "/admin/", "/admin/login.php", "/admin?page=1",
                     "/administrator"]:
        event = {
            "timestamp": datetime(2026, 5, 27, 10, 0, 0),
            "username": None,
            "source_ip": "10.0.0.99",
            "resource": resource,
            "action": "http_request",
            "status_code": "403",
        }
        detected = len(detect_unauthorized_access([event], config)) > 0
        scored_as_restricted = (
            score_violation(_unauth(resource), config)["impact"] != default_impact
        )
        assert detected == scored_as_restricted, (
            f"{resource}: detection={detected} but scoring={scored_as_restricted}"
        )
        verdicts.append(detected)

    # The cases must cover both outcomes, or agreement proves nothing.
    assert True in verdicts and False in verdicts
