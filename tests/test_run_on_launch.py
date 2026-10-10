"""pipeline.run_on_launch gates the startup batch read in main().

run_pipeline() reads both log files in full at launch. Setting
pipeline.run_on_launch to false skips that read; LogWatcher.start() must still
be called exactly as before, so live tailing is unaffected. A missing key means
true, so an older config keeps the previous behaviour.

Schema creation and the storage.clear_on_start wipe run at startup in main()
itself, independently of run_on_launch.
"""
import os
import sqlite3
import sys
from unittest.mock import ANY, MagicMock, patch

import pytest
import yaml

import main as cybermon_main
from main import _run_on_launch
from src.storage.db import init_db

# Imported before _run_main patches QApplication/QIcon. A module first imported
# while those patches are active copies the mocks into its own namespace and
# keeps them for the rest of the session, breaking later tests that build a
# real MainWindow.
import src.gui.main_window  # noqa: E402,F401


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# _run_on_launch helper
# ---------------------------------------------------------------------------

def test_run_on_launch_true():
    assert _run_on_launch({"pipeline": {"run_on_launch": True}}) is True


def test_run_on_launch_false():
    assert _run_on_launch({"pipeline": {"run_on_launch": False}}) is False


def test_run_on_launch_missing_key_defaults_to_true():
    assert _run_on_launch({}) is True
    assert _run_on_launch({"pipeline": {}}) is True


def test_run_on_launch_empty_pipeline_block_defaults_to_true():
    """A bare `pipeline:` line loads as None and must not crash."""
    assert _run_on_launch({"pipeline": None}) is True


# ---------------------------------------------------------------------------
# main() wiring — Qt window, watcher and pipeline are mocked
# ---------------------------------------------------------------------------

def _db(tmp_path):
    return os.path.join(str(tmp_path), "data", "cybermon.db")


def _run_main(tmp_path, pipeline_block, storage_extra=None, run_pipeline=None):
    """Run main() against a temp config; return (run_pipeline, LogWatcher, window) mocks."""
    auth_log = str(tmp_path / "auth.log")
    web_log = str(tmp_path / "access.log")
    cfg = {
        "mode": "standalone",
        "setup_complete": True,
        "storage": {"db_path": "data/cybermon.db", **(storage_extra or {})},
        "auth_log_path": auth_log,
        "web_log_path": web_log,
    }
    if pipeline_block is not None:
        cfg["pipeline"] = pipeline_block
    os.makedirs(tmp_path / "config", exist_ok=True)
    with open(tmp_path / "config" / "config.yaml", "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh)

    run_pipeline = run_pipeline or MagicMock()
    watcher_cls = MagicMock()
    window_cls = MagicMock()
    app = MagicMock()
    app.exec.return_value = 0

    # QApplication is mocked here, so QIcon must be too: main() builds the app
    # icon, and a real QIcon with no QApplication aborts the whole process.
    with patch.object(sys, "argv", ["main.py"]), \
         patch.object(cybermon_main, "_data_path",
                      lambda rel: os.path.join(str(tmp_path), rel)), \
         patch.object(cybermon_main, "run_pipeline", run_pipeline), \
         patch("PyQt6.QtWidgets.QApplication", return_value=app), \
         patch("PyQt6.QtGui.QIcon"), \
         patch("src.ingestion.watcher.LogWatcher", watcher_cls), \
         patch("src.gui.main_window.MainWindow", window_cls):
        with pytest.raises(SystemExit):
            cybermon_main.main()

    return run_pipeline, watcher_cls, window_cls, auth_log, web_log


def test_false_skips_pipeline_but_still_starts_watcher(tmp_path):
    run_pipeline, watcher_cls, window_cls, auth_log, web_log = _run_main(
        tmp_path, {"run_on_launch": False})

    run_pipeline.assert_not_called()
    watcher_cls.return_value.start.assert_called_once_with(
        auth_log=auth_log, web_log=web_log, on_violation=ANY, on_event=ANY)
    window_cls.return_value.show_error_banner.assert_not_called()


def test_true_runs_pipeline_and_starts_watcher(tmp_path):
    run_pipeline, watcher_cls, _window, auth_log, web_log = _run_main(
        tmp_path, {"run_on_launch": True})

    run_pipeline.assert_called_once_with(auth_log, web_log, ANY)
    watcher_cls.return_value.start.assert_called_once_with(
        auth_log=auth_log, web_log=web_log, on_violation=ANY, on_event=ANY)


def test_missing_key_runs_pipeline(tmp_path):
    run_pipeline, watcher_cls, _window, _a, _w = _run_main(tmp_path, None)

    run_pipeline.assert_called_once()
    watcher_cls.return_value.start.assert_called_once()


# ---------------------------------------------------------------------------
# Startup schema + clear_on_start — run in main(), independent of run_on_launch
# ---------------------------------------------------------------------------

def _tables(db_path):
    if not os.path.exists(db_path):
        return set()
    conn = sqlite3.connect(db_path)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    return names


def _seed_row(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO violations (violation_type, timestamp, detail) "
        "VALUES ('off_hours_login', '2026-09-13T03:00:00', 'kept')")
    conn.commit()
    conn.close()


def _kept_rows(db_path):
    conn = sqlite3.connect(db_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM violations WHERE detail='kept'").fetchone()[0]
    conn.close()
    return n


def test_false_on_fresh_database_still_creates_schema(tmp_path):
    """Regression: skipping run_pipeline() on a fresh install must not leave the
    live watcher writing to a table-less DB."""
    assert not os.path.exists(_db(tmp_path))

    _run_main(tmp_path, {"run_on_launch": False})

    assert {"events", "violations", "risk_scores"} <= _tables(_db(tmp_path))


def test_true_on_fresh_database_creates_schema_in_main(tmp_path):
    """main() creates the schema itself; with run_pipeline() mocked out the
    tables still exist, so schema creation no longer depends on the pipeline."""
    _run_main(tmp_path, {"run_on_launch": True})

    assert {"events", "violations", "risk_scores"} <= _tables(_db(tmp_path))


def test_false_with_clear_on_start_true_wipes(tmp_path):
    """The wipe runs on launch even when run_pipeline() does not."""
    _seed_row(_db(tmp_path))

    run_pipeline, _w, _win, _a, _b = _run_main(
        tmp_path, {"run_on_launch": False}, {"clear_on_start": True})

    run_pipeline.assert_not_called()
    assert _kept_rows(_db(tmp_path)) == 0


def test_false_with_clear_on_start_false_keeps_rows(tmp_path):
    _seed_row(_db(tmp_path))

    _run_main(tmp_path, {"run_on_launch": False}, {"clear_on_start": False})

    assert _kept_rows(_db(tmp_path)) == 1


def test_true_with_clear_on_start_true_wipes_before_pipeline(tmp_path):
    """run_pipeline() is mocked (it cannot wipe), yet the seeded row is already
    gone when it is called — the wipe happens in main(), before the pipeline."""
    db_path = _db(tmp_path)
    _seed_row(db_path)
    rows_at_call = []
    run_pipeline = MagicMock(side_effect=lambda *_a: rows_at_call.append(_kept_rows(db_path)))

    _run_main(tmp_path, {"run_on_launch": True}, {"clear_on_start": True},
              run_pipeline=run_pipeline)

    assert rows_at_call == [0]


def test_true_with_clear_on_start_false_keeps_rows(tmp_path):
    _seed_row(_db(tmp_path))

    run_pipeline, _w, _win, _a, _b = _run_main(
        tmp_path, {"run_on_launch": True}, {"clear_on_start": False})

    run_pipeline.assert_called_once()
    assert _kept_rows(_db(tmp_path)) == 1


def test_watcher_start_identical_whether_pipeline_runs_or_not(tmp_path):
    """The gate must not change how the watcher is started."""
    _rp, on_cls, _w1, _a1, _b1 = _run_main(tmp_path / "on", {"run_on_launch": True})
    _rp, off_cls, _w2, _a2, _b2 = _run_main(tmp_path / "off", {"run_on_launch": False})

    on_call = on_cls.return_value.start.call_args
    off_call = off_cls.return_value.start.call_args
    assert set(on_call.kwargs) == set(off_call.kwargs) == {
        "auth_log", "web_log", "on_violation", "on_event"}
    assert on_call.args == off_call.args == ()
    assert on_cls.call_count == off_cls.call_count == 1


# ---------------------------------------------------------------------------
# Config files
# ---------------------------------------------------------------------------

def test_run_on_launch_present_in_both_config_files():
    """The key ships in both files.

    config_default.yaml is the template a fresh install copies, so it must stay
    true: false there would silently skip startup analysis for every new user.
    config/config.yaml is the local copy: it may omit the key (missing = true)
    or set either value (false = live-tail-only demo setup).
    """
    default = _load("config/config_default.yaml").get("pipeline") or {}
    assert default.get("run_on_launch") is True, "config_default.yaml must ship run_on_launch: true"

    live = _load("config/config.yaml").get("pipeline") or {}
    assert isinstance(live.get("run_on_launch", True), bool), "run_on_launch must be true or false"
