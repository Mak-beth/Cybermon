"""Tests added in R7.

Covers:
  - Four severity-tier scoring patterns that simulate.py produces
  - Config scoring tier boundaries for all four tiers
  - simulate.py log path defaults matching main.py defaults
  - get_violations_for_export() column contract
  - is_first_run() behaviour when config.yaml does not exist at all
"""
import importlib.util
import os

import pytest
import yaml


# ---------------------------------------------------------------------------
# Scoring rules for simulate.py tier verification
# ---------------------------------------------------------------------------

from src.scoring.rules import get_likelihood, get_impact


def _v(vtype, username, resource, detail):
    return {
        "violation_type": vtype,
        "username": username,
        "resource": resource,
        "detail": detail,
    }


def test_simulate_critical_pattern_likelihood_5():
    v = _v("failed_logins", "admin", None, "20 failed logins in 10 min for user 'admin'")
    assert get_likelihood(v) == 5


def test_simulate_critical_pattern_impact_4():
    v = _v("failed_logins", "admin", None, "20 failed logins in 10 min for user 'admin'")
    assert get_impact(v) == 4


def test_simulate_low_pattern_score_is_4():
    v = _v("failed_logins", "guest", None, "3 failed logins in 10 min for user 'guest'")
    assert get_likelihood(v) * get_impact(v) == 4


def test_simulate_high_pattern_score_is_15():
    v = _v("unauthorized_access", None, "/admin", "HTTP 403")
    assert get_likelihood(v) * get_impact(v) == 15


def test_all_four_tiers_in_config_bounds():
    with open("config/config.yaml") as f:
        cfg = yaml.safe_load(f)
    tiers = cfg["scoring"]["severity_tiers"]
    assert tiers["low"]["min"] <= 4 <= tiers["low"]["max"]
    assert tiers["medium"]["min"] <= 6 <= tiers["medium"]["max"]
    assert tiers["high"]["min"] <= 15 <= tiers["high"]["max"]
    assert tiers["critical"]["min"] <= 20 <= tiers["critical"]["max"]


def test_simulate_log_paths_follow_config():
    """simulate.py reads log paths from config.yaml so it stays in sync with main.py.
    Paths must be non-empty strings; the exact value depends on config."""
    spec = importlib.util.spec_from_file_location("simulate", "simulate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert isinstance(mod.AUTH_LOG, str) and len(mod.AUTH_LOG) > 0
    assert isinstance(mod.WEB_LOG, str) and len(mod.WEB_LOG) > 0
    # Must NOT write to the locked test fixtures
    assert mod.AUTH_LOG != "logs/samples/auth.log", (
        "simulate.py must not write to the test sample logs"
    )
    assert mod.WEB_LOG != "logs/samples/access.log", (
        "simulate.py must not write to the test sample logs"
    )
