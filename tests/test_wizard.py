"""Tests for wizard helper functions.

These tests target the two pure-IO functions exported by src.gui.wizard:
    is_first_run(config_path)
    write_wizard_config(settings, config_path)

No QApplication is required.  SetupWizard is a deferred factory function;
importing it does not touch PyQt6.  This file imports only the two pure
helpers, so no Qt installation is needed to run the suite.
"""
import os

import pytest
import yaml

from src.gui.wizard import is_first_run, write_wizard_config

# ---------------------------------------------------------------------------
# Shared settings fixtures
# ---------------------------------------------------------------------------

_STANDALONE_SETTINGS = {
    "mode": "standalone",
    "auth_log_path": "logs/auth.log",
    "web_log_path": "logs/access.log",
    "business_hours_start": "09:00",
    "business_hours_end": "17:00",
    "business_days": [0, 1, 2, 3, 4],
    "brute_force_threshold": 3,
    "brute_force_window": 5,
}

_NETWORK_SETTINGS = {
    "mode": "network",
    "auth_log_path": "logs/auth.log",
    "web_log_path": "logs/access.log",
    "business_hours_start": "08:00",
    "business_hours_end": "18:00",
    "business_days": [0, 1, 2, 3, 4],
    "brute_force_threshold": 5,
    "brute_force_window": 10,
    "server_ip": "192.168.1.100",
    "server_port": 5001,
}


# ---------------------------------------------------------------------------
# write_wizard_config tests
# ---------------------------------------------------------------------------

def test_wizard_writes_standalone_config(tmp_path):
    config_path = str(tmp_path / "config.yaml")

    write_wizard_config(_STANDALONE_SETTINGS, config_path)

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    assert cfg["mode"] == "standalone"
    assert cfg["setup_complete"] is True
    assert cfg["auth_log_path"] == "logs/auth.log"
    assert cfg["web_log_path"] == "logs/access.log"
    assert cfg["detection"]["failed_logins"]["threshold"] == 3
    assert cfg["detection"]["failed_logins"]["time_window_minutes"] == 5
    assert cfg["detection"]["off_hours_logins"]["business_hours_start"] == "09:00"
    assert cfg["detection"]["off_hours_logins"]["business_hours_end"] == "17:00"
    assert cfg["detection"]["off_hours_logins"]["business_days"] == [0, 1, 2, 3, 4]


def test_wizard_writes_network_config(tmp_path):
    config_path = str(tmp_path / "config.yaml")

    write_wizard_config(_NETWORK_SETTINGS, config_path)

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    assert cfg["mode"] == "network"
    assert cfg["setup_complete"] is True
    assert cfg["server"]["ip"] == "192.168.1.100"
    assert cfg["server"]["port"] == 5001


# ---------------------------------------------------------------------------
# is_first_run tests
# ---------------------------------------------------------------------------

def test_first_run_detection_missing_key(tmp_path):
    config_path = str(tmp_path / "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump({"mode": "standalone"}, f)

    assert is_first_run(config_path) is True


def test_first_run_detection_complete(tmp_path):
    config_path = str(tmp_path / "config.yaml")
    with open(config_path, "w") as f:
        yaml.dump({"mode": "standalone", "setup_complete": True}, f)

    assert is_first_run(config_path) is False
