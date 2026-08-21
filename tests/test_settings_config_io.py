"""Settings config IO: validation, atomic save, scoped restore, and security.

Covers Objective 4 (NFR-01) usability work: scoring values are editable from the
Settings panel instead of by hand-editing YAML. These tests target the Qt-free
config_io layer, so they run headless.
"""
import hashlib
import os
import shutil

import pytest
import yaml

from src.gui import config_io
from src.gui.config_io import (
    ConfigError,
    load_config,
    restore_section,
    sanitise_entries,
    validate_score,
    validate_scoring_block,
    validate_tiers,
    write_config_atomic,
)

REPO_CONFIG = "config/config.yaml"
REPO_DEFAULTS = "config/config_default.yaml"


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


@pytest.fixture
def cfg_pair(tmp_path):
    """A writable copy of the real config + defaults, isolated per test."""
    cfg_path = tmp_path / "config.yaml"
    def_path = tmp_path / "config_default.yaml"
    shutil.copyfile(REPO_CONFIG, cfg_path)
    shutil.copyfile(REPO_DEFAULTS, def_path)
    return str(cfg_path), str(def_path)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

def test_valid_edit_saves_and_reads_back(cfg_pair):
    cfg_path, _ = cfg_pair
    cfg = load_config(cfg_path)
    cfg["scoring"]["rules"]["off_hours_high_user_impact"] = 4
    cfg["scoring"]["rules"]["high_impact_users"] = ["root", "admin", "svc"]
    write_config_atomic(cfg, cfg_path)

    reread = load_config(cfg_path)
    assert reread["scoring"]["rules"]["off_hours_high_user_impact"] == 4
    assert reread["scoring"]["rules"]["high_impact_users"] == ["root", "admin", "svc"]


def test_save_preserves_line_endings(cfg_pair):
    """A text-mode write would silently rewrite LF as CRLF on Windows."""
    cfg_path, def_path = cfg_pair
    for path in (cfg_path, def_path):
        before = open(path, "rb").read()
        was_crlf = b"\r\n" in before
        write_config_atomic(load_config(path), path)
        after = open(path, "rb").read()
        assert (b"\r\n" in after) == was_crlf
        assert b"\r\r\n" not in after


# ---------------------------------------------------------------------------
# SECURITY: api_key must never be altered by a save
# ---------------------------------------------------------------------------

def test_api_key_unchanged_after_save(cfg_pair):
    cfg_path, _ = cfg_pair
    original = load_config(cfg_path)["server"]["api_key"]
    cfg = load_config(cfg_path)
    cfg["scoring"]["rules"]["off_hours_default_impact"] = 2
    write_config_atomic(cfg, cfg_path)
    assert load_config(cfg_path)["server"]["api_key"] == original


def test_api_key_unchanged_after_both_restores(cfg_pair):
    cfg_path, def_path = cfg_pair
    original = load_config(cfg_path)["server"]["api_key"]
    for section in ("scoring", "detection"):
        cfg = load_config(cfg_path)
        write_config_atomic(
            restore_section(cfg, load_config(def_path), section), cfg_path)
        assert load_config(cfg_path)["server"]["api_key"] == original


# ---------------------------------------------------------------------------
# Scoped restore — must not touch anything outside its section
# ---------------------------------------------------------------------------

PRESERVED = ("auth_log_path", "web_log_path", "setup_complete", "mode")


@pytest.mark.parametrize("section", ["scoring", "detection"])
def test_restore_preserves_user_settings(cfg_pair, section):
    cfg_path, def_path = cfg_pair
    cfg = load_config(cfg_path)
    # Simulate a user whose live settings differ from the defaults.
    cfg["auth_log_path"] = "C:/ProgramData/ssh/logs/sshd.log"
    cfg["web_log_path"] = "logs/live/access.log"
    cfg["setup_complete"] = True
    cfg["mode"] = "network"
    cfg["ui"] = {"theme": "dark"}
    cfg["storage"]["db_path"] = "data/custom.db"
    write_config_atomic(cfg, cfg_path)

    before = load_config(cfg_path)
    restored = restore_section(before, load_config(def_path), section)
    write_config_atomic(restored, cfg_path)
    after = load_config(cfg_path)

    for key in PRESERVED:
        assert after[key] == before[key], f"{section} restore changed {key}"
    assert after["ui"] == before["ui"]
    assert after["server"] == before["server"]
    assert after["agent"] == before["agent"]
    assert after["storage"] == before["storage"]


def test_restore_scoring_resets_only_scoring(cfg_pair):
    cfg_path, def_path = cfg_pair
    cfg = load_config(cfg_path)
    cfg["scoring"]["rules"]["off_hours_high_user_impact"] = 1
    cfg["detection"]["failed_logins"]["threshold"] = 99
    write_config_atomic(cfg, cfg_path)

    restored = restore_section(load_config(cfg_path), load_config(def_path), "scoring")
    defaults = load_config(def_path)
    assert restored["scoring"]["rules"] == defaults["scoring"]["rules"]
    assert restored["detection"]["failed_logins"]["threshold"] == 99   # untouched


def test_restore_detection_resets_only_detection(cfg_pair):
    cfg_path, def_path = cfg_pair
    cfg = load_config(cfg_path)
    cfg["detection"]["failed_logins"]["threshold"] = 99
    cfg["scoring"]["rules"]["off_hours_high_user_impact"] = 1
    write_config_atomic(cfg, cfg_path)

    restored = restore_section(load_config(cfg_path), load_config(def_path), "detection")
    defaults = load_config(def_path)
    assert restored["detection"] == defaults["detection"]
    assert restored["scoring"]["rules"]["off_hours_high_user_impact"] == 1  # untouched


def test_restore_rejects_unknown_section(cfg_pair):
    cfg_path, def_path = cfg_pair
    with pytest.raises(ConfigError):
        restore_section(load_config(cfg_path), load_config(def_path), "server")


# ---------------------------------------------------------------------------
# Validation — invalid input must never reach disk
# ---------------------------------------------------------------------------

def test_rejected_save_leaves_file_byte_identical(cfg_pair):
    """Validation happens before any write: the file must not change at all."""
    cfg_path, _ = cfg_pair
    before = _sha(cfg_path)

    bad = load_config(cfg_path)
    bad["scoring"]["rules"]["off_hours_default_impact"] = 9      # out of 1-5
    bad["scoring"]["severity_tiers"]["low"] = {"min": 1, "max": 99}
    errors = validate_scoring_block(bad["scoring"])
    assert errors
    # caller must not write when errors are present
    assert _sha(cfg_path) == before


@pytest.mark.parametrize("value", [0, 6, -1, 99, "3", 3.5, True, None])
def test_out_of_range_or_wrong_type_scores_rejected(value):
    assert validate_score(value, "impact")


def test_in_range_scores_accepted():
    for value in (1, 2, 3, 4, 5):
        assert validate_score(value, "impact") == []


def test_hand_edited_out_of_range_config_rejected_on_load(cfg_pair):
    """A config edited outside the app must still be caught."""
    cfg_path, _ = cfg_pair
    cfg = load_config(cfg_path)
    cfg["scoring"]["rules"]["failed_login_high_user_impact"] = 42
    write_config_atomic(cfg, cfg_path)
    errors = validate_scoring_block(load_config(cfg_path)["scoring"])
    assert any("failed_login_high_user_impact" in e for e in errors)


# ---------------------------------------------------------------------------
# Severity tiers
# ---------------------------------------------------------------------------

def test_valid_tiers_accepted():
    assert validate_tiers({
        "low": {"min": 1, "max": 4}, "medium": {"min": 5, "max": 9},
        "high": {"min": 10, "max": 16}, "critical": {"min": 17, "max": 25},
    }) == []


def test_overlapping_tiers_rejected():
    errs = validate_tiers({
        "low": {"min": 1, "max": 6}, "medium": {"min": 5, "max": 9},
        "high": {"min": 10, "max": 16}, "critical": {"min": 17, "max": 25},
    })
    assert any("overlap" in e for e in errs)


def test_gap_between_tiers_rejected():
    errs = validate_tiers({
        "low": {"min": 1, "max": 4}, "medium": {"min": 7, "max": 9},
        "high": {"min": 10, "max": 16}, "critical": {"min": 17, "max": 25},
    })
    assert any("gap" in e for e in errs)


def test_inverted_tier_range_rejected():
    errs = validate_tiers({
        "low": {"min": 4, "max": 1}, "medium": {"min": 5, "max": 9},
        "high": {"min": 10, "max": 16}, "critical": {"min": 17, "max": 25},
    })
    assert any("greater than" in e for e in errs)


def test_tiers_must_cover_full_range():
    errs = validate_tiers({
        "low": {"min": 2, "max": 4}, "medium": {"min": 5, "max": 9},
        "high": {"min": 10, "max": 16}, "critical": {"min": 17, "max": 20},
    })
    assert any("must start at 1" in e for e in errs)
    assert any("must end at 25" in e for e in errs)


# ---------------------------------------------------------------------------
# List sanitisation
# ---------------------------------------------------------------------------

def test_list_strips_whitespace_and_skips_blanks():
    entries, errors = sanitise_entries(["  root ", "", "  ", "admin"], "Users")
    assert entries == ["root", "admin"]
    assert errors == []


def test_list_rejects_control_characters_and_null_bytes():
    for bad in ["ro\x00ot", "adm\x1bin", "user\x07"]:
        _entries, errors = sanitise_entries([bad, "ok"], "Users")
        assert any("control characters" in e for e in errors)


def test_list_rejects_over_length_entry():
    _entries, errors = sanitise_entries(["a" * (config_io.MAX_ENTRY_LEN + 1), "ok"], "Users")
    assert any("longer than" in e for e in errors)


def test_list_rejects_duplicates():
    _entries, errors = sanitise_entries(["root", "root"], "Users")
    assert any("duplicate" in e for e in errors)


def test_list_rejects_empty_result():
    _entries, errors = sanitise_entries(["", "   "], "Users")
    assert any("at least one entry" in e for e in errors)


def test_list_rejects_too_many_entries():
    many = [f"user{i}" for i in range(config_io.MAX_ENTRIES + 5)]
    _entries, errors = sanitise_entries(many, "Users")
    assert any("more than" in e for e in errors)


# ---------------------------------------------------------------------------
# SECURITY: user strings are only ever compared, never executed
# ---------------------------------------------------------------------------

def test_config_io_never_executes_or_path_builds_user_values():
    """Static guard: no eval/exec/os.system/subprocess in the config IO layer."""
    import inspect
    source = inspect.getsource(config_io)
    for forbidden in ("eval(", "exec(", "os.system", "subprocess", "__import__("):
        assert forbidden not in source, f"{forbidden} present in config_io"


def test_scoring_rules_are_only_used_for_membership_comparison():
    """A shell-ish username is stored and compared verbatim, never interpreted."""
    from src.scoring.rules import get_impact
    nasty = "; rm -rf / #"
    config = {"scoring": {
        "severity_tiers": {"low": {"min": 1, "max": 4}, "medium": {"min": 5, "max": 9},
                           "high": {"min": 10, "max": 16}, "critical": {"min": 17, "max": 25}},
        "rules": {"high_impact_users": [nasty], "off_hours_default_impact": 3,
                  "off_hours_high_user_impact": 5},
    }}
    violation = {"violation_type": "off_hours_login", "username": nasty,
                 "resource": None, "detail": "x"}
    assert get_impact(violation, config) == 5          # matched, not executed


# ---------------------------------------------------------------------------
# Atomicity / recoverability
# ---------------------------------------------------------------------------

def test_previous_contents_kept_as_single_rolling_backup(cfg_pair):
    cfg_path, _ = cfg_pair
    original = open(cfg_path, "rb").read()

    cfg = load_config(cfg_path)
    cfg["scoring"]["rules"]["off_hours_default_impact"] = 2
    write_config_atomic(cfg, cfg_path)

    assert os.path.exists(cfg_path + ".prev")
    assert open(cfg_path + ".prev", "rb").read() == original
    # exactly one rolling backup, no accumulation
    directory = os.path.dirname(cfg_path)
    assert len([f for f in os.listdir(directory) if f.endswith(".prev")]) == 1


def test_no_temp_files_left_behind(cfg_pair):
    cfg_path, _ = cfg_pair
    write_config_atomic(load_config(cfg_path), cfg_path)
    directory = os.path.dirname(cfg_path)
    assert [f for f in os.listdir(directory) if f.startswith(".cfg-")] == []


def test_load_reports_safe_message_for_missing_file(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config(str(tmp_path / "nope.yaml"))
    message = str(exc.value)
    assert "nope.yaml" not in message and str(tmp_path) not in message


def test_load_reports_safe_message_for_malformed_yaml(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_bytes(b"scoring:\n  rules: [unclosed\n")
    with pytest.raises(ConfigError) as exc:
        load_config(str(bad))
    message = str(exc.value)
    assert str(tmp_path) not in message
    assert "Traceback" not in message
