import copy
import pytest
import yaml

from src.ingestion.preprocessor import preprocess_log_file
from src.detection.detector import run_detection
from src.detection.rules.failed_logins import detect_failed_logins
from src.detection.rules.unauthorized_access import detect_unauthorized_access
from src.detection.rules.off_hours import detect_off_hours_logins

VIOLATION_KEYS = {"violation_type", "timestamp", "username", "source_ip", "resource", "detail"}


@pytest.fixture
def config():
    with open("config/config.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture
def all_events():
    auth = preprocess_log_file("logs/samples/auth.log", "auth")
    web = preprocess_log_file("logs/samples/access.log", "web")
    return auth + web


@pytest.fixture
def auth_events():
    return preprocess_log_file("logs/samples/auth.log", "auth")


@pytest.fixture
def web_events():
    return preprocess_log_file("logs/samples/access.log", "web")


# --- run_detection ---

def test_run_detection_returns_at_least_3_violations(config, all_events):
    violations = run_detection(all_events, config)
    assert len(violations) >= 3


def test_run_detection_contains_failed_logins(config, all_events):
    violations = run_detection(all_events, config)
    assert any(v["violation_type"] == "failed_logins" for v in violations)


def test_run_detection_contains_unauthorized_access(config, all_events):
    violations = run_detection(all_events, config)
    assert any(v["violation_type"] == "unauthorized_access" for v in violations)


def test_run_detection_contains_off_hours_login(config, all_events):
    violations = run_detection(all_events, config)
    assert any(v["violation_type"] == "off_hours_login" for v in violations)


def test_all_violations_have_schema_keys(config, all_events):
    violations = run_detection(all_events, config)
    for v in violations:
        assert VIOLATION_KEYS.issubset(set(v.keys())), f"Missing keys in: {v}"


def test_run_detection_does_not_modify_events(config, all_events):
    original = copy.deepcopy(all_events)
    run_detection(all_events, config)
    assert all_events == original


# --- failed_logins rule ---

def test_failed_logins_detects_admin_brute_force(config, auth_events):
    violations = detect_failed_logins(auth_events, config)
    assert any(v["username"] == "admin" for v in violations)


def test_failed_logins_one_violation_per_username(config, auth_events):
    violations = detect_failed_logins(auth_events, config)
    usernames = [v["username"] for v in violations]
    assert len(usernames) == len(set(usernames))


def test_failed_logins_threshold_change_affects_count(config, auth_events):
    low_cfg = copy.deepcopy(config)
    low_cfg["detection"]["failed_logins"]["threshold"] = 2
    high_cfg = copy.deepcopy(config)
    high_cfg["detection"]["failed_logins"]["threshold"] = 100

    low = detect_failed_logins(auth_events, low_cfg)
    high = detect_failed_logins(auth_events, high_cfg)
    assert len(low) >= len(high)
    assert len(high) == 0


def test_failed_logins_empty_events(config):
    assert detect_failed_logins([], config) == []


# --- unauthorized_access rule ---

def test_unauthorized_access_detects_admin_403(config, web_events):
    violations = detect_unauthorized_access(web_events, config)
    assert any(v["resource"] == "/admin" for v in violations)


def test_unauthorized_access_detects_config_401(config, web_events):
    violations = detect_unauthorized_access(web_events, config)
    assert any(v["resource"] == "/config" for v in violations)


def test_unauthorized_access_ignores_200s(config, web_events):
    ok_events = [e for e in web_events if e["status_code"] == "200"]
    violations = detect_unauthorized_access(ok_events, config)
    assert len(violations) == 0


def test_unauthorized_access_count_matches_log(config, web_events):
    violations = detect_unauthorized_access(web_events, config)
    # 5x /admin 403 + 3x /config 401 + 1x /wp-admin 403 + 1x /.env 403 = 10
    assert len(violations) == 10


# --- off_hours rule ---

def test_off_hours_detects_alice_night_login(config, auth_events):
    violations = detect_off_hours_logins(auth_events, config)
    assert any(v["username"] == "alice" for v in violations)


def test_off_hours_only_flags_successful_logins(config, auth_events):
    violations = detect_off_hours_logins(auth_events, config)
    for v in violations:
        matched = [e for e in auth_events if e["username"] == v["username"]
                   and e["timestamp"] == v["timestamp"]]
        assert all(e["status_code"] == "SUCCESS" for e in matched)


def test_off_hours_business_hours_login_not_flagged(config):
    from datetime import datetime
    inside = [{
        "timestamp": datetime(2026, 5, 27, 10, 0, 0),  # Wednesday 10:00
        "username": "john",
        "source_ip": "10.0.0.1",
        "resource": None,
        "action": "ssh_login",
        "status_code": "SUCCESS",
    }]
    violations = detect_off_hours_logins(inside, config)
    assert len(violations) == 0


# --- R11-D2: prefix matching for restricted resources ---

def _web_event(resource: str, status: str = "403"):
    from datetime import datetime
    return {
        "timestamp": datetime(2026, 5, 27, 10, 0, 0),
        "username": None,
        "source_ip": "10.0.0.99",
        "resource": resource,
        "action": "http_request",
        "status_code": status,
    }


_UNAUTH_CONFIG = {"detection": {"unauthorized_access": {
    "restricted_resources": ["/admin", "/wp-admin", "/phpmyadmin", "/config", "/.env"],
    "trigger_codes": [403, 401],
}}}


def test_restricted_subpath_detected():
    violations = detect_unauthorized_access([_web_event("/admin/users")], _UNAUTH_CONFIG)
    assert len(violations) == 1


def test_restricted_query_string_detected():
    violations = detect_unauthorized_access([_web_event("/admin?page=1")], _UNAUTH_CONFIG)
    assert len(violations) == 1


def test_exact_match_still_works():
    violations = detect_unauthorized_access([_web_event("/admin")], _UNAUTH_CONFIG)
    assert len(violations) == 1


def test_non_restricted_similar_name():
    """Prefix match, not substring — /administrator is a different path."""
    violations = detect_unauthorized_access([_web_event("/administrator")], _UNAUTH_CONFIG)
    assert len(violations) == 0


# --- R11-D3: /var/www/html removed from default config ---

def test_var_www_html_not_in_default_restricted_resources():
    with open("config/config_default.yaml") as f:
        default_cfg = yaml.safe_load(f)
    restricted = default_cfg["detection"]["unauthorized_access"]["restricted_resources"]
    assert "/var/www/html" not in restricted


# --- R11-D4: password spray detection ---

def _spray_event(username: str, ip: str, second: int):
    from datetime import datetime
    return {
        "timestamp": datetime(2026, 5, 27, 10, 0, second),
        "username": username,
        "source_ip": ip,
        "resource": None,
        "action": "ssh_login",
        "status_code": "FAILED",
    }


def _spray_config(threshold: int = 3) -> dict:
    return {"detection": {"failed_logins": {
        "threshold": threshold,
        "time_window_minutes": 10,
    }}}


def test_spray_across_multiple_usernames_detected():
    events = [
        _spray_event(f"user{i}", "66.66.66.66", second=i) for i in range(5)
    ]
    violations = detect_failed_logins(events, _spray_config(threshold=3))
    assert len(violations) == 1
    assert violations[0]["violation_type"] == "failed_logins"
    assert "spray" in violations[0]["detail"].lower()
    assert violations[0]["source_ip"] == "66.66.66.66"


def test_spray_below_threshold_not_detected():
    events = [
        _spray_event("user1", "66.66.66.66", second=0),
        _spray_event("user2", "66.66.66.66", second=1),
    ]
    violations = detect_failed_logins(events, _spray_config(threshold=3))
    assert len(violations) == 0


def test_spray_does_not_double_count_with_brute_force():
    """5 fails each on two usernames from one IP: two brute-force violations,
    no third spray entry for the same IP."""
    events = (
        [_spray_event("victim-a", "66.66.66.66", second=i) for i in range(5)] +
        [_spray_event("victim-b", "66.66.66.66", second=10 + i) for i in range(5)]
    )
    violations = detect_failed_logins(events, _spray_config(threshold=3))
    assert len(violations) <= 2
