"""R11-E ground-truth detection accuracy test.

A labelled synthetic log where every expected detection (and every expected
NON-detection) is known in advance.  Serves as a confusion-matrix substitute:
the test fails if any planted violation is missed (false negative) or any
known-clean input produces a violation (false positive).

Expected detections (8 total):
    1 brute force  — root,  20 FAILED from 10.0.0.1   → Critical (L5 x I4 = 20)
    1 brute force  — guest,  3 FAILED from 10.0.0.2   → Low      (L2 x I2 = 4)
    5 unauthorized — GET /admin 403 from 10.0.0.3     → High     (L3 x I5 = 15) each
                     (the rule emits one violation per offending request)
    1 off-hours    — alice, SUCCESS at 03:00 Monday   → Medium   (L2 x I3 = 6)

Expected NON-detections:
    nobody — 1 FAILED (below threshold)
    bob    — SUCCESS at 10:00 Monday (inside business hours)
    /about — 3 GET returning 200 (clean traffic)
"""
from datetime import datetime, timedelta

from src.ingestion.parser import parse_auth_log_line, parse_access_log_line
from src.ingestion.preprocessor import normalize_event
from src.detection.detector import run_detection
from src.scoring.scorer import score_all_violations

_CONFIG = {
    "detection": {
        "failed_logins": {"threshold": 2, "time_window_minutes": 10},
        "unauthorized_access": {
            "restricted_resources": ["/admin", "/wp-admin", "/phpmyadmin",
                                     "/config", "/.env"],
            "trigger_codes": [403, 401],
        },
        "off_hours_logins": {
            "business_days": [0, 1, 2, 3, 4],
            "business_hours_start": "08:00",
            "business_hours_end": "18:00",
        },
    },
    "scoring": {
        "severity_tiers": {
            "low": {"min": 1, "max": 4}, "medium": {"min": 5, "max": 9},
            "high": {"min": 10, "max": 16}, "critical": {"min": 17, "max": 25},
        },
        "rules": {
            "high_impact_users": ["root", "admin"],
            "high_impact_resources": ["/admin", "/.env", "/phpmyadmin"],
            "med_impact_resources": ["/config", "/wp-admin"],
            "failed_login_likelihood_bands": [
                {"max_count": 5, "likelihood": 2},
                {"max_count": 9, "likelihood": 3},
                {"max_count": 19, "likelihood": 4},
                {"max_count": 99999, "likelihood": 5},
            ],
            "unauthorized_access_default_likelihood": 3,
            "off_hours_default_likelihood": 2,
            "off_hours_default_impact": 3,
            "failed_login_high_user_impact": 4,
            "failed_login_default_impact": 2,
            "unauthorized_access_high_resource_impact": 5,
            "unauthorized_access_med_resource_impact": 3,
            "unauthorized_access_default_impact": 2,
        },
    },
}


def _last_monday() -> datetime:
    """Most recent past Monday — keeps the weekday deterministic year-round.

    Auth log timestamps carry no year; the preprocessor assigns the current
    year, so a hardcoded date would change weekday from year to year.
    """
    today = datetime.now()
    monday = today - timedelta(days=today.weekday() or 7)
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def _auth_ts(dt: datetime) -> str:
    return dt.strftime("%b %d %H:%M:%S")


def _web_ts(dt: datetime) -> str:
    return dt.strftime("%d/%b/%Y:%H:%M:%S +0000")


def _build_events() -> list[dict]:
    monday = _last_monday()
    noon = monday.replace(hour=12)

    auth_lines = []
    # 20 FAILED for root within 5 minutes → brute force, Critical
    for i in range(20):
        t = noon + timedelta(seconds=i * 10)
        auth_lines.append(
            f"{_auth_ts(t)} server sshd[3{i:03d}]: "
            f"Failed password for root from 10.0.0.1 port 22 ssh2"
        )
    # 3 FAILED for guest within 5 minutes → brute force, Low
    for i in range(3):
        t = noon + timedelta(minutes=1, seconds=i * 20)
        auth_lines.append(
            f"{_auth_ts(t)} server sshd[4{i:03d}]: "
            f"Failed password for guest from 10.0.0.2 port 22 ssh2"
        )
    # 1 FAILED for nobody — below threshold, must NOT be detected
    auth_lines.append(
        f"{_auth_ts(noon)} server sshd[5000]: "
        f"Failed password for nobody from 10.0.0.9 port 22 ssh2"
    )
    # SUCCESS for alice at 03:00 Monday — off-hours, must be detected
    alice_t = monday.replace(hour=3)
    auth_lines.append(
        f"{_auth_ts(alice_t)} server sshd[5001]: "
        f"Accepted password for alice from 10.0.0.8 port 22 ssh2"
    )
    # SUCCESS for bob at 10:00 Monday — business hours, must NOT be detected
    bob_t = monday.replace(hour=10)
    auth_lines.append(
        f"{_auth_ts(bob_t)} server sshd[5002]: "
        f"Accepted password for bob from 10.0.0.7 port 22 ssh2"
    )

    web_lines = []
    # 5 GET /admin → 403 — unauthorized access, must be detected (one per request)
    for i in range(5):
        t = noon + timedelta(minutes=2, seconds=i * 5)
        web_lines.append(
            f'10.0.0.3 - - [{_web_ts(t)}] "GET /admin HTTP/1.1" 403 512 "-" "curl/8.0"'
        )
    # 3 GET /about → 200 — clean traffic, must NOT be detected
    for i in range(3):
        t = noon + timedelta(minutes=3, seconds=i * 5)
        web_lines.append(
            f'10.0.0.4 - - [{_web_ts(t)}] "GET /about HTTP/1.1" 200 1024 "-" "Mozilla/5.0"'
        )

    events = []
    for line in auth_lines:
        parsed = parse_auth_log_line(line)
        assert parsed is not None, f"parser rejected labelled line: {line}"
        events.append(normalize_event(parsed, "auth"))
    for line in web_lines:
        parsed = parse_access_log_line(line)
        assert parsed is not None, f"parser rejected labelled line: {line}"
        events.append(normalize_event(parsed, "web"))
    return events


def test_ground_truth_detection_accuracy():
    events = _build_events()
    violations = run_detection(events, _CONFIG)
    scored = score_all_violations(violations, _CONFIG)

    by_type: dict[str, list] = {}
    for v in scored:
        by_type.setdefault(v["violation_type"], []).append(v)

    # --- exact counts: 2 brute force + 5 unauthorized + 1 off-hours = 8 ---
    assert len(scored) == 8, [
        (v["violation_type"], v.get("username"), v.get("resource")) for v in scored
    ]
    assert len(by_type.get("failed_logins", [])) == 2
    assert len(by_type.get("unauthorized_access", [])) == 5
    assert len(by_type.get("off_hours_login", [])) == 1

    # --- severities for each labelled detection ---
    brute = {v["username"]: v for v in by_type["failed_logins"]}
    assert set(brute) == {"root", "guest"}
    assert brute["root"]["risk_score"] >= 17       # Critical
    assert brute["root"]["severity"] == "Critical"
    assert brute["guest"]["risk_score"] <= 9       # Low or Medium
    assert brute["guest"]["severity"] in ("Low", "Medium")

    for v in by_type["unauthorized_access"]:
        assert v["resource"] == "/admin"
        assert v["risk_score"] >= 10               # High
        assert v["severity"] == "High"

    off_hours = by_type["off_hours_login"][0]
    assert off_hours["username"] == "alice"
    assert off_hours["risk_score"] <= 9            # Medium
    assert off_hours["severity"] == "Medium"

    # --- zero false positives on known-clean inputs ---
    assert all(v.get("username") != "nobody" for v in scored)
    assert all(v.get("username") != "bob" for v in scored)
    assert all(v.get("resource") != "/about" for v in scored)
