"""Settings panel "Save & Re-score" button behaviour.

Runs Qt offscreen. Modal dialogs are stubbed so nothing blocks.
"""
import hashlib
import os
import shutil
import sqlite3

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox   # noqa: E402

from src.gui import config_io                            # noqa: E402
from src.storage.db import init_db                       # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def quiet_dialogs(monkeypatch):
    """Capture dialog text instead of showing modal windows."""
    shown = {"info": [], "warn": []}
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown["info"].append(a[2]) or QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: shown["warn"].append(a[2]) or QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    return shown


@pytest.fixture
def panel_env(tmp_path, qapp, quiet_dialogs):
    """Settings panel wired to a temp config + temp DB holding one violation."""
    cfg_path = tmp_path / "config.yaml"
    shutil.copyfile("config/config.yaml", cfg_path)
    shutil.copyfile("config/config_default.yaml", tmp_path / "config_default.yaml")

    db_path = str(tmp_path / "cybermon.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO violations (violation_type, timestamp, username, source_ip,"
        " resource, detail, source_host) VALUES "
        "('off_hours_login','2026-08-20T03:14:00','root','10.0.0.1',NULL,'d','h')")
    vid = cur.lastrowid
    cur.execute(
        "INSERT INTO risk_scores (violation_id, likelihood, impact, risk_score,"
        " severity, source_host) VALUES (?,2,3,6,'Medium','h')", (vid,))
    conn.commit()
    conn.close()

    cfg = config_io.load_config(str(cfg_path))
    cfg["storage"]["db_path"] = db_path
    cfg["scoring"]["rules"]["off_hours_high_user_impact"] = 3   # flat to start
    config_io.write_config_atomic(cfg, str(cfg_path))

    from src.gui.settings_panel import SettingsPanel
    panel = SettingsPanel(config_io.load_config(str(cfg_path)),
                          config_path=str(cfg_path))
    return panel, str(cfg_path), db_path, vid, quiet_dialogs


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _score(db_path, vid):
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT risk_score, severity FROM risk_scores WHERE violation_id=?",
        (vid,)).fetchone()
    conn.close()
    return row


def test_invalid_input_writes_nothing_and_does_not_rescore(panel_env):
    panel, cfg_path, db_path, vid, dialogs = panel_env
    before_cfg = _sha(cfg_path)
    before_score = _score(db_path, vid)

    panel._tier_inputs["low"]["max"].setValue(9)      # overlaps medium (5-9)
    panel._save_and_rescore()

    assert _sha(cfg_path) == before_cfg               # byte-identical
    assert _score(db_path, vid) == before_score       # no re-score happened
    assert dialogs["warn"], "user should have been told why"


def test_valid_save_and_rescore_applies_new_value_once(panel_env, monkeypatch):
    panel, cfg_path, db_path, vid, dialogs = panel_env
    assert _score(db_path, vid) == (6, "Medium")

    calls = []
    import src.gui.settings_panel as sp
    real = sp.rescore_violations
    monkeypatch.setattr(sp, "rescore_violations",
                        lambda db, cfg: calls.append(db) or real(db, cfg))

    panel._score_inputs["off_hours_high_user_impact"].setValue(5)
    panel._save_and_rescore()

    assert len(calls) == 1, "pipeline must run exactly once per click"
    assert _score(db_path, vid) == (10, "High")
    saved = config_io.load_config(cfg_path)
    assert saved["scoring"]["rules"]["off_hours_high_user_impact"] == 5


def test_rescored_signal_emitted_for_view_refresh(panel_env):
    panel, _cfg, _db, _vid, _d = panel_env
    fired = []
    panel.rescored.connect(lambda: fired.append(True))
    panel._save_and_rescore()
    assert fired == [True]


def test_button_is_not_reentrant(panel_env, monkeypatch):
    """A second click while a re-score runs must be ignored."""
    panel, _cfg, _db, _vid, _d = panel_env
    calls = []

    import src.gui.settings_panel as sp

    def reentrant(db, cfg):
        calls.append(db)
        panel._save_and_rescore()      # simulate a second click mid-run
        return {"total": 0, "updated": 0, "changed": 0}

    monkeypatch.setattr(sp, "rescore_violations", reentrant)
    panel._save_and_rescore()
    assert len(calls) == 1


def test_rescore_failure_is_reported_safely(panel_env, monkeypatch):
    """A failure shows a short message, keeps config valid, and does not crash."""
    panel, cfg_path, db_path, vid, dialogs = panel_env
    before_score = _score(db_path, vid)

    import src.gui.settings_panel as sp
    monkeypatch.setattr(sp, "rescore_violations",
                        lambda db, cfg: (_ for _ in ()).throw(RuntimeError("boom")))

    panel._save_and_rescore()          # must not raise

    assert dialogs["warn"], "failure should be surfaced"
    message = dialogs["warn"][-1]
    assert "boom" not in message and "Traceback" not in message
    assert str(cfg_path) not in message and os.sep + "config" not in message
    assert _score(db_path, vid) == before_score
    config_io.load_config(cfg_path)    # config still parses


def test_detection_change_adds_restart_notice(panel_env):
    panel, _cfg, _db, _vid, dialogs = panel_env
    panel._threshold.setValue(panel._threshold.value() + 1)   # detection change
    panel._save_and_rescore()
    assert any("restart" in m.lower() for m in dialogs["info"])


def test_scoring_only_change_says_no_restart_needed(panel_env):
    panel, _cfg, _db, _vid, dialogs = panel_env
    panel._score_inputs["off_hours_default_impact"].setValue(2)
    panel._save_and_rescore()
    message = dialogs["info"][-1]
    assert "No restart needed" in message
    assert "detection settings" not in message


def test_api_key_unchanged_after_save_and_rescore(panel_env):
    panel, cfg_path, _db, _vid, _d = panel_env
    before = config_io.load_config(cfg_path)["server"]["api_key"]
    panel._score_inputs["off_hours_high_user_impact"].setValue(4)
    panel._save_and_rescore()
    assert config_io.load_config(cfg_path)["server"]["api_key"] == before
