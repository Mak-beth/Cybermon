"""Live log-path reload: LiveMonitor restart, Settings signal, MainWindow wiring.

The restart is forward-only: it moves the tail threads to the new files and
never re-runs run_pipeline() or _prepare_database().
"""
import os
import socket
import sqlite3
import time

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ingestion.watcher import LogWatcher                    # noqa: E402
from src.live_monitor import LiveMonitor, missing_log_paths     # noqa: E402
from src.storage.db import init_db                              # noqa: E402

DEFAULT_CONFIG = "config/config_default.yaml"


@pytest.fixture
def config():
    """The reference config, so thresholds don't depend on local config.yaml edits."""
    with open(DEFAULT_CONFIG, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "live.db")
    init_db(path)
    return path


def _pair(tmp_path, tag):
    auth = tmp_path / f"{tag}_auth.log"
    web = tmp_path / f"{tag}_access.log"
    auth.write_text("")
    web.write_text("")
    return str(auth), str(web)


def _append_failed(path, user, n=1):
    with open(path, "a", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(f"Sep 16 03:00:{i:02d} server sshd[1]: "
                     f"Failed password for {user} from 10.9.9.9 port 22 ssh2\n")


def _events_for(db_path, user):
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM events WHERE username=?", (user,)).fetchone()[0]
    conn.close()
    return n


def _wait_until(predicate, timeout=5.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


_marker = [0]


def _wait_until_tailing(db_path, auth_path, timeout=6.0):
    """A tail thread seeks to the end when it opens a file, so a line written
    before that is skipped. Append uniquely named markers until one lands."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _marker[0] += 1
        user = f"ready{_marker[0]}"
        _append_failed(auth_path, user)
        if _wait_until(lambda: _events_for(db_path, user) > 0, timeout=0.7):
            return
    raise AssertionError(f"no tail thread picked up {auth_path}")


def _buffer_len(monitor, user):
    key = f"{socket.gethostname()}:{user}"
    return len(monitor._watcher._failed_buffer.get(key, ()))


# ---------------------------------------------------------------------------
# LogWatcher lifecycle
# ---------------------------------------------------------------------------

def test_start_after_stop_does_not_revive_previous_threads(tmp_path, config):
    """Regression: start() used to clear the stop Event the old threads were
    still watching, so stop() then start() left four threads on two paths."""
    a1, w1 = _pair(tmp_path, "old")
    a2, w2 = _pair(tmp_path, "new")
    watcher = LogWatcher(config)
    watcher.start(a1, w1, lambda v: None)
    old_threads = list(watcher._threads)

    watcher.stop()
    watcher.start(a2, w2, lambda v: None)          # no wait in between
    try:
        assert _wait_until(lambda: not any(t.is_alive() for t in old_threads), timeout=3)
        assert len(watcher._threads) == 2
        assert all(t.is_alive() for t in watcher._threads)
    finally:
        watcher.stop()
        watcher.join(3)


def test_join_reports_that_threads_exited(tmp_path, config):
    auth, web = _pair(tmp_path, "join")
    watcher = LogWatcher(config)
    watcher.start(auth, web, lambda v: None)
    watcher.stop()
    assert watcher.join(3) is True
    assert not any(t.is_alive() for t in watcher._threads)


# ---------------------------------------------------------------------------
# LiveMonitor
# ---------------------------------------------------------------------------

def test_rapid_restarts_leave_one_thread_pair_on_the_newest_paths(tmp_path, config, db):
    pairs = [_pair(tmp_path, f"run{i}") for i in range(4)]
    monitor = LiveMonitor(config, db_path=db)
    monitor.start(*pairs[0])
    all_threads = list(monitor._watcher._threads)
    try:
        for auth, web in pairs[1:]:
            assert monitor.restart(auth, web) == []        # back to back, no waiting
            all_threads += monitor._watcher._threads

        current = monitor._watcher._threads
        previous = [t for t in all_threads if t not in current]
        assert len(current) == 2 and all(t.is_alive() for t in current)
        assert len(previous) == 6
        assert not any(t.is_alive() for t in previous)
        assert (monitor.auth_log, monitor.web_log) == pairs[-1]

        # Behaviour, not just thread objects: only the newest auth file is tailed.
        _wait_until_tailing(db, pairs[-1][0])
        for auth, _web in pairs[:-1]:
            _append_failed(auth, "stale_path_user")
        _append_failed(pairs[-1][0], "current_path_user")
        assert _wait_until(lambda: _events_for(db, "current_path_user") == 1)
        time.sleep(1.0)     # longer than a poll interval: a stale tail would have fired
        assert _events_for(db, "stale_path_user") == 0
    finally:
        monitor.stop()


def test_failed_login_state_is_empty_immediately_after_restart(tmp_path, config, db):
    threshold = config["detection"]["failed_logins"]["threshold"]
    a1, w1 = _pair(tmp_path, "before")
    a2, w2 = _pair(tmp_path, "after")
    monitor = LiveMonitor(config, db_path=db)
    monitor.start(a1, w1)
    try:
        _wait_until_tailing(db, a1)
        _append_failed(a1, "victim", n=threshold + 1)       # raises one violation
        assert _wait_until(lambda: _buffer_len(monitor, "victim") == threshold + 1)
        assert _wait_until(lambda: bool(monitor._watcher._violation_cooldown))

        assert monitor.restart(a2, w2) == []

        assert monitor._watcher._failed_buffer == {}
        assert monitor._watcher._violation_cooldown == {}

        # A failure on the new file starts a fresh count, not old count + 1.
        _wait_until_tailing(db, a2)
        _append_failed(a2, "victim")
        assert _wait_until(lambda: _buffer_len(monitor, "victim") == 1)
    finally:
        monitor.stop()


def test_restart_onto_missing_path_starts_nothing_and_keeps_previous_files(tmp_path, config, db):
    a1, w1 = _pair(tmp_path, "live")
    _a2, w2 = _pair(tmp_path, "other")
    missing = str(tmp_path / "not_there" / "auth.log")
    monitor = LiveMonitor(config, db_path=db)
    monitor.start(a1, w1)
    threads_before = list(monitor._watcher._threads)
    try:
        assert monitor.restart(missing, w2) == [missing]

        # No watcher was started against the missing path, and nothing retries it.
        assert monitor._watcher._threads == threads_before
        assert all(t.is_alive() for t in threads_before)
        assert (monitor.auth_log, monitor.web_log) == (a1, w1)
        _wait_until_tailing(db, a1)                         # still monitoring
    finally:
        monitor.stop()


def test_missing_log_paths(tmp_path):
    real = tmp_path / "real.log"
    real.write_text("")
    nope = str(tmp_path / "nope.log")
    assert missing_log_paths(str(real), str(real)) == []
    assert missing_log_paths("", str(real)) == [""]
    assert missing_log_paths(str(tmp_path), str(real)) == [str(tmp_path)]   # a directory
    assert missing_log_paths(nope, nope) == [nope, nope]


def test_stop_waits_for_the_threads_to_exit(tmp_path, config, db):
    auth, web = _pair(tmp_path, "stop")
    monitor = LiveMonitor(config, db_path=db)
    monitor.start(auth, web)
    threads = list(monitor._watcher._threads)
    assert monitor.stop() is True
    assert not any(t.is_alive() for t in threads)


# ---------------------------------------------------------------------------
# Settings + MainWindow wiring (Qt offscreen)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def gui_env(tmp_path, qapp, monkeypatch, config, db):
    """Temp config file and DB. Dialogs are captured and theme persistence is
    stubbed, so no modal window blocks and QSettings is never written."""
    from PyQt6.QtWidgets import QMessageBox
    from src.gui import data_access, main_window

    shown = []
    ok = QMessageBox.StandardButton.Ok
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.append(a[2]) or ok))
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: shown.append(a[2]) or ok))
    monkeypatch.setattr(data_access, "_db_path", db)
    monkeypatch.setattr(main_window._theme, "apply_theme", lambda dark: None)

    auth, web = _pair(tmp_path, "gui")
    cfg = yaml.safe_load(yaml.safe_dump(config))              # deep copy
    cfg["auth_log_path"], cfg["web_log_path"] = auth, web
    cfg["storage"]["db_path"] = db
    cfg_path = str(tmp_path / "config.yaml")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)
    return cfg, cfg_path, auth, web, shown


def _window(cfg, cfg_path, monitor):
    from src.gui.main_window import MainWindow
    return MainWindow(cfg, config_path=cfg_path, monitor=monitor)


def test_settings_receives_the_resolved_config_path(gui_env):
    cfg, cfg_path, _a, _w, _shown = gui_env
    window = _window(cfg, cfg_path, monitor=None)
    try:
        assert window._panels[4]._config_path == cfg_path
    finally:
        window.close()


def test_settings_emits_log_paths_changed_only_when_a_path_changes(gui_env, tmp_path):
    cfg, cfg_path, auth, _web, _shown = gui_env
    from src.gui.settings_panel import SettingsPanel
    panel = SettingsPanel(cfg, config_path=cfg_path)
    emitted = []
    panel.log_paths_changed.connect(lambda a, w: emitted.append((a, w)))

    panel._save()                                   # nothing changed
    assert emitted == []

    _new_auth, new_web = _pair(tmp_path, "changed")
    panel._web_input.setText(new_web)
    panel._save()
    assert emitted == [(auth, new_web)]

    panel._save()                                   # unchanged since last save
    assert emitted == [(auth, new_web)]


def test_path_change_restarts_monitor_on_the_new_files(gui_env, tmp_path, db):
    cfg, cfg_path, auth, web, _shown = gui_env
    monitor = LiveMonitor(cfg, db_path=db)
    monitor.start(auth, web)
    window = _window(cfg, cfg_path, monitor)
    try:
        new_auth, new_web = _pair(tmp_path, "switched")
        settings = window._panels[4]
        settings._auth_input.setText(new_auth)
        settings._web_input.setText(new_web)
        settings._save()

        assert (monitor.auth_log, monitor.web_log) == (new_auth, new_web)
        assert window._warning_banner.isHidden()
        _wait_until_tailing(db, new_auth)
    finally:
        window.close()
        monitor.stop()


def test_restart_onto_missing_path_shows_banner_instead_of_tailing_it(gui_env, tmp_path, db):
    cfg, cfg_path, auth, web, _shown = gui_env
    monitor = LiveMonitor(cfg, db_path=db)
    monitor.start(auth, web)
    threads_before = list(monitor._watcher._threads)
    window = _window(cfg, cfg_path, monitor)
    try:
        missing = str(tmp_path / "gone" / "auth.log")
        settings = window._panels[4]
        settings._auth_input.setText(missing)
        settings._save()

        assert not window._warning_banner.isHidden()
        assert missing in window._banner_text.text()
        assert "previous files" in window._banner_text.text()
        assert monitor._watcher._threads == threads_before
        assert all(t.is_alive() for t in threads_before)
        assert monitor.auth_log == auth

        # A later save onto files that exist restarts and clears the warning.
        good_auth, _good_web = _pair(tmp_path, "recovered")
        settings._auth_input.setText(good_auth)
        settings._save()
        assert monitor.auth_log == good_auth
        assert window._warning_banner.isHidden()
    finally:
        window.close()
        monitor.stop()


def test_successful_restart_does_not_clear_an_error_banner(gui_env, tmp_path, db):
    cfg, cfg_path, auth, web, _shown = gui_env
    monitor = LiveMonitor(cfg, db_path=db)
    monitor.start(auth, web)
    window = _window(cfg, cfg_path, monitor)
    try:
        window.show_error_banner("startup pipeline failed")
        new_auth, _new_web = _pair(tmp_path, "after_error")
        window._panels[4]._auth_input.setText(new_auth)
        window._panels[4]._save()

        assert monitor.auth_log == new_auth
        assert not window._warning_banner.isHidden()
        assert "startup pipeline failed" in window._banner_text.text()
    finally:
        window.close()
        monitor.stop()


def test_close_event_stops_live_monitoring(gui_env, db):
    cfg, cfg_path, auth, web, _shown = gui_env
    monitor = LiveMonitor(cfg, db_path=db)
    monitor.start(auth, web)
    threads = list(monitor._watcher._threads)
    window = _window(cfg, cfg_path, monitor)
    window.show()
    window.close()
    assert not any(t.is_alive() for t in threads)


def test_close_event_without_a_monitor_is_safe(gui_env):
    cfg, cfg_path, _a, _w, _shown = gui_env
    window = _window(cfg, cfg_path, monitor=None)
    window.show()
    window.close()                                  # must not raise


# ---------------------------------------------------------------------------
# main() hands the window the resolved config path and the monitor
# ---------------------------------------------------------------------------

def test_main_passes_config_path_and_monitor_to_the_window(tmp_path):
    from tests.test_run_on_launch import _run_main
    _rp, watcher_cls, window_cls, auth_log, web_log = _run_main(
        tmp_path, {"run_on_launch": False})

    kwargs = window_cls.call_args.kwargs
    assert kwargs["config_path"] == os.path.join(str(tmp_path), "config/config.yaml")
    monitor = kwargs["monitor"]
    assert isinstance(monitor, LiveMonitor)
    assert monitor._watcher is watcher_cls.return_value
    assert (monitor.auth_log, monitor.web_log) == (auth_log, web_log)
    assert monitor.db_path == os.path.join(str(tmp_path), "data/cybermon.db")
