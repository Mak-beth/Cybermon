"""Config load / validate / atomic-save for the Settings panel.

This is the ONE place config.yaml is written from the GUI. The settings panel
delegates here rather than opening the file itself, so the atomic-write and
validation guarantees hold for every save.

Deliberately Qt-free: validation and IO are testable headless.

Security notes
--------------
* Reads use yaml.safe_load only — never yaml.load.
* Writes are atomic: temp file in the same directory, fsync, os.replace. A
  crash mid-write can never leave a truncated config.yaml (which would brick
  the app on next launch).
* The previous contents are kept as a single rolling ``.prev`` file.
* Values from the UI are treated as untrusted: sanitised for control
  characters, length and count; numeric fields are range-checked here, not
  only in the widget, so a hand-edited config is rejected too.
* Callers must never surface absolute paths or stack traces to the UI; the
  helpers here raise ConfigError with short, safe messages and log detail.
"""
from __future__ import annotations

import logging
import os
import tempfile

import yaml

logger = logging.getLogger(__name__)

# Bounds for the 1-5 likelihood/impact model (IR Table 3.2).
SCORE_MIN, SCORE_MAX = 1, 5
# Severity tiers must collectively cover this range with no gap or overlap.
TIER_MIN, TIER_MAX = 1, 25
# Limits on user-editable list fields, to keep config growth bounded.
MAX_ENTRY_LEN = 256
MAX_ENTRIES = 100

TIER_NAMES = ("low", "medium", "high", "critical")

# scoring.rules keys that are plain 1-5 integers.
NUMERIC_RULE_KEYS = (
    "off_hours_default_likelihood",
    "off_hours_default_impact",
    "off_hours_high_user_impact",
    "unauthorized_access_default_likelihood",
    "unauthorized_access_high_resource_impact",
    "unauthorized_access_med_resource_impact",
    "unauthorized_access_default_impact",
    "failed_login_high_user_impact",
    "failed_login_default_impact",
)

# scoring.rules keys that are lists of strings.
LIST_RULE_KEYS = (
    "high_impact_users",
    "high_impact_resources",
    "med_impact_resources",
)

# Config sections the "restore defaults" buttons may touch. Anything not named
# here is preserved verbatim — notably auth_log_path, web_log_path,
# setup_complete, mode, ui, server (incl. api_key), agent and storage.
RESTORABLE_SECTIONS = {
    "scoring":   ("rules", "severity_tiers"),
    "detection": ("failed_logins", "unauthorized_access", "off_hours_logins"),
}


class ConfigError(Exception):
    """Raised with a short, user-safe message (no paths, no stack traces)."""


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    """Read a config file with safe_load. Raises ConfigError on failure."""
    try:
        with open(path, "rb") as fh:
            return yaml.safe_load(fh.read().decode("utf-8")) or {}
    except FileNotFoundError:
        raise ConfigError("Configuration file not found.") from None
    except (OSError, yaml.YAMLError) as exc:
        logger.error("config_io: failed to read config at %s: %s", path, exc)
        raise ConfigError("Configuration file could not be read or is not valid YAML.") from None


# ---------------------------------------------------------------------------
# Sanitisation / validation
# ---------------------------------------------------------------------------

def sanitise_entries(raw: list, field_label: str) -> tuple[list[str], list[str]]:
    """Clean a user-edited list field. Returns (entries, errors).

    Values are only ever compared against log fields — never evaluated, never
    used to build a path or a shell command.
    """
    entries: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()

    for item in raw:
        value = str(item).strip()
        if not value:
            continue                       # blank lines are skipped, not an error
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            errors.append(f"{field_label}: entry contains control characters.")
            continue
        if len(value) > MAX_ENTRY_LEN:
            errors.append(f"{field_label}: entry longer than {MAX_ENTRY_LEN} characters.")
            continue
        if value in seen:
            errors.append(f"{field_label}: duplicate entry '{value}'.")
            continue
        seen.add(value)
        entries.append(value)

    if not entries:
        errors.append(f"{field_label}: must contain at least one entry.")
    if len(entries) > MAX_ENTRIES:
        errors.append(f"{field_label}: more than {MAX_ENTRIES} entries.")
    return entries, errors


def validate_score(value, label: str) -> list[str]:
    """A likelihood/impact value must be an int within SCORE_MIN..SCORE_MAX."""
    if isinstance(value, bool) or not isinstance(value, int):
        return [f"{label}: must be a whole number."]
    if not (SCORE_MIN <= value <= SCORE_MAX):
        return [f"{label}: must be between {SCORE_MIN} and {SCORE_MAX}."]
    return []


def validate_tiers(tiers: dict) -> list[str]:
    """Severity tiers must be ordered, contiguous, non-overlapping, 1..25."""
    errors: list[str] = []
    bounds = []
    for name in TIER_NAMES:
        tier = (tiers or {}).get(name)
        if not isinstance(tier, dict) or "min" not in tier or "max" not in tier:
            return [f"Severity tiers: '{name}' is missing a min/max value."]
        lo, hi = tier["min"], tier["max"]
        for val, which in ((lo, "min"), (hi, "max")):
            if isinstance(val, bool) or not isinstance(val, int):
                errors.append(f"Severity tiers: {name} {which} must be a whole number.")
        if errors:
            return errors
        if lo > hi:
            errors.append(f"Severity tiers: {name} min ({lo}) is greater than max ({hi}).")
        bounds.append((name, lo, hi))
    if errors:
        return errors

    ordered = sorted(bounds, key=lambda b: b[1])
    if ordered[0][1] != TIER_MIN:
        errors.append(f"Severity tiers: lowest tier must start at {TIER_MIN}.")
    if ordered[-1][2] != TIER_MAX:
        errors.append(f"Severity tiers: highest tier must end at {TIER_MAX}.")
    for (n1, _lo1, hi1), (n2, lo2, _hi2) in zip(ordered, ordered[1:]):
        if lo2 <= hi1:
            errors.append(f"Severity tiers: {n1} and {n2} overlap.")
        elif lo2 != hi1 + 1:
            errors.append(f"Severity tiers: gap between {n1} and {n2}.")
    return errors


def validate_scoring_block(scoring: dict) -> list[str]:
    """Validate a whole scoring block (rules + severity_tiers)."""
    errors: list[str] = []
    rules = (scoring or {}).get("rules", {}) or {}
    for key in NUMERIC_RULE_KEYS:
        if key in rules:
            errors += validate_score(rules[key], key)
    for key in LIST_RULE_KEYS:
        if key in rules:
            value = rules[key]
            if not isinstance(value, list):
                errors.append(f"{key}: must be a list.")
            else:
                _entries, errs = sanitise_entries(value, key)
                errors += errs
    errors += validate_tiers((scoring or {}).get("severity_tiers", {}))
    return errors


# ---------------------------------------------------------------------------
# Restore defaults (scoped)
# ---------------------------------------------------------------------------

def restore_section(cfg: dict, defaults: dict, section: str) -> dict:
    """Return a copy of cfg with only `section`'s known sub-keys reset.

    Every other key — log paths, setup_complete, mode, ui, server.api_key,
    agent, storage — is carried through untouched.
    """
    if section not in RESTORABLE_SECTIONS:
        raise ConfigError("Unknown settings section.")

    import copy
    updated = copy.deepcopy(cfg)
    default_section = (defaults or {}).get(section, {}) or {}
    updated.setdefault(section, {})
    for sub_key in RESTORABLE_SECTIONS[section]:
        if sub_key in default_section:
            updated[section][sub_key] = copy.deepcopy(default_section[sub_key])
    return updated


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

def _detect_newline(path: str) -> bytes:
    """Return the dominant line ending of an existing file (default LF)."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return b"\n"
    return b"\r\n" if data.count(b"\r\n") else b"\n"


def write_config_atomic(cfg: dict, path: str) -> None:
    """Serialise cfg and replace `path` atomically, keeping one .prev backup.

    Preserves the file's existing line endings (a text-mode write on Windows
    would silently rewrite an LF file as CRLF).
    """
    newline = _detect_newline(path)
    try:
        text = yaml.dump(cfg, default_flow_style=False, sort_keys=False)
    except yaml.YAMLError as exc:
        logger.error("config_io: could not serialise config: %s", exc)
        raise ConfigError("Settings could not be saved (invalid values).") from None

    payload = text.replace("\r\n", "\n").replace("\n", newline.decode()).encode("utf-8")
    directory = os.path.dirname(os.path.abspath(path)) or "."

    tmp_path = None
    try:
        # Keep the last known-good copy before replacing anything.
        if os.path.exists(path):
            with open(path, "rb") as src:
                previous = src.read()
            with open(path + ".prev", "wb") as dst:
                dst.write(previous)

        fd, tmp_path = tempfile.mkstemp(prefix=".cfg-", dir=directory)
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())          # durable before the swap
        os.replace(tmp_path, path)         # atomic on Windows and POSIX
        tmp_path = None
    except OSError as exc:
        logger.error("config_io: atomic write failed for %s: %s", path, exc)
        raise ConfigError("Settings could not be saved to disk.") from None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError as exc:
                logger.warning("config_io: could not remove temp file: %s", exc)
