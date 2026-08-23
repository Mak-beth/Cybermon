"""R12-B: the startup table wipe is an explicit config flag.

run_pipeline() empties events/violations/risk_scores on every launch so each run
reflects the current log files (demo-rebuild design). That behaviour is
unchanged by default; storage.clear_on_start makes it explicit and switchable,
which is what NFR-05 ("retrieve findings persistently across sessions") needs.
"""
import copy
import sqlite3

import pytest
import yaml

from main import run_pipeline
from src.storage.db import init_db

AUTH_LOG = "logs/samples/auth.log"
WEB_LOG = "logs/samples/access.log"


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture
def seeded(tmp_path):
    """Temp DB holding one pre-existing violation, and a config pointing at it."""
    db_path = str(tmp_path / "clear.db")
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO events (timestamp, username, source_ip, resource, action,"
        " status_code, log_type, source_host, raw_log) VALUES "
        "('2026-08-20T03:14:00','seeduser','10.0.0.1',NULL,'ssh_login',"
        "'SUCCESS','auth','seed-host','seeded raw line')")
    cur.execute(
        "INSERT INTO violations (violation_type, timestamp, username, source_ip,"
        " resource, detail, source_host) VALUES "
        "('off_hours_login','2026-08-20T03:14:00','seeduser','10.0.0.1',NULL,"
        "'seeded','seed-host')")
    vid = cur.lastrowid
    cur.execute(
        "INSERT INTO risk_scores (violation_id, likelihood, impact, risk_score,"
        " severity, source_host) VALUES (?,2,3,6,'Medium','seed-host')", (vid,))
    conn.commit()
    conn.close()

    cfg = _load("config/config.yaml")
    cfg["storage"] = {"db_path": db_path}
    return cfg, db_path


def _seeded_rows(db_path):
    conn = sqlite3.connect(db_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM violations WHERE username='seeduser'").fetchone()[0]
    conn.close()
    return n


def test_clear_on_start_true_wipes_tables(seeded):
    """With the flag true the seeded rows are gone; only rebuilt rows remain."""
    cfg, db_path = seeded
    cfg["storage"]["clear_on_start"] = True
    assert _seeded_rows(db_path) == 1

    run_pipeline(AUTH_LOG, WEB_LOG, cfg)

    assert _seeded_rows(db_path) == 0


def test_clear_on_start_false_preserves_existing_rows(seeded):
    """With the flag false the seeded rows survive the run."""
    cfg, db_path = seeded
    cfg["storage"]["clear_on_start"] = False

    run_pipeline(AUTH_LOG, WEB_LOG, cfg)

    assert _seeded_rows(db_path) == 1


def test_clear_on_start_missing_key_defaults_to_true(seeded):
    """An older config with no such key must behave exactly as before."""
    cfg, db_path = seeded
    cfg["storage"].pop("clear_on_start", None)
    assert "clear_on_start" not in cfg["storage"]

    run_pipeline(AUTH_LOG, WEB_LOG, cfg)

    assert _seeded_rows(db_path) == 0


def test_clear_on_start_present_in_both_config_files():
    """The key ships in both the live config and the reference template."""
    for path in ("config/config.yaml", "config/config_default.yaml"):
        storage = _load(path).get("storage", {})
        assert "clear_on_start" in storage, f"missing from {path}"
        assert storage["clear_on_start"] is True, f"not true in {path}"
