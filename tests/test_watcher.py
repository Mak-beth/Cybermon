import threading
import time
import yaml
import pytest

from src.ingestion.watcher import tail_file, LogWatcher


@pytest.fixture
def config():
    with open("config/config.yaml") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# tail_file tests
# ---------------------------------------------------------------------------

def test_tail_file_calls_callback_for_new_lines(tmp_path):
    log_file = tmp_path / "test.log"
    log_file.write_text("old line\n")

    received = []
    done = threading.Event()

    def cb(line, log_type):
        received.append(line)
        if len(received) >= 2:
            done.set()

    stop = threading.Event()
    t = threading.Thread(
        target=tail_file,
        args=(str(log_file), "auth", cb, 0.05, stop),
        daemon=True,
    )
    t.start()
    time.sleep(0.15)  # let watcher open the file and seek to end

    with open(str(log_file), "a") as f:
        f.write("new line 1\n")
        f.write("new line 2\n")

    done.wait(timeout=3)
    stop.set()

    assert "new line 1" in received
    assert "new line 2" in received


def test_tail_file_skips_existing_lines(tmp_path):
    log_file = tmp_path / "test.log"
    log_file.write_text("existing line 1\nexisting line 2\n")

    received = []
    done = threading.Event()

    def cb(line, log_type):
        received.append(line)
        done.set()

    stop = threading.Event()
    t = threading.Thread(
        target=tail_file,
        args=(str(log_file), "auth", cb, 0.05, stop),
        daemon=True,
    )
    t.start()
    time.sleep(0.15)

    with open(str(log_file), "a") as f:
        f.write("trigger line\n")

    done.wait(timeout=3)
    stop.set()

    assert "existing line 1" not in received
    assert "existing line 2" not in received
    assert "trigger line" in received


def test_tail_file_passes_log_type_to_callback(tmp_path):
    log_file = tmp_path / "test.log"
    log_file.touch()

    received_types = []
    done = threading.Event()

    def cb(line, log_type):
        received_types.append(log_type)
        done.set()

    stop = threading.Event()
    t = threading.Thread(
        target=tail_file,
        args=(str(log_file), "web", cb, 0.05, stop),
        daemon=True,
    )
    t.start()
    time.sleep(0.1)

    with open(str(log_file), "a") as f:
        f.write("some line\n")

    done.wait(timeout=3)
    stop.set()

    assert received_types == ["web"]


def test_tail_file_survives_temporarily_missing_file(tmp_path):
    missing = str(tmp_path / "does_not_exist.log")

    received = []
    done = threading.Event()

    def cb(line, log_type):
        received.append(line)
        done.set()

    stop = threading.Event()
    t = threading.Thread(
        target=tail_file,
        args=(missing, "auth", cb, 0.05, stop),
        daemon=True,
    )
    t.start()

    # Thread should be alive after retrying for a moment
    time.sleep(0.3)
    assert t.is_alive(), "tail_file should not crash on missing file"

    # Create the file and write a line — watcher should eventually pick it up
    with open(missing, "w") as f:
        pass  # create empty file first

    time.sleep(0.15)  # let watcher open the now-existing file

    with open(missing, "a") as f:
        f.write("late line\n")

    done.wait(timeout=3)
    stop.set()

    assert "late line" in received


# ---------------------------------------------------------------------------
# LogWatcher tests
# ---------------------------------------------------------------------------

def test_logwatcher_spawns_two_daemon_threads(tmp_path, config):
    auth_log = tmp_path / "auth.log"
    web_log = tmp_path / "web.log"
    auth_log.touch()
    web_log.touch()

    watcher = LogWatcher(config)
    watcher.start(str(auth_log), str(web_log), lambda v: None)
    time.sleep(0.1)

    assert len(watcher._threads) == 2
    assert all(t.daemon for t in watcher._threads)

    watcher.stop()


def test_logwatcher_calls_on_violation_on_brute_force(tmp_path, config):
    auth_log = tmp_path / "auth.log"
    web_log = tmp_path / "web.log"
    auth_log.touch()
    web_log.touch()

    violations = []
    got_violation = threading.Event()

    def on_violation(v):
        violations.append(v)
        got_violation.set()

    watcher = LogWatcher(config)
    watcher.start(str(auth_log), str(web_log), on_violation)
    time.sleep(0.2)  # let threads open files and seek to end

    # threshold is 5, so writing 6 FAILED lines in the same minute triggers it
    with open(str(auth_log), "a") as f:
        for i in range(6):
            f.write(
                f"May 28 10:00:{i:02d} server sshd[1234]: "
                f"Failed password for bruteman from 10.0.0.1 port 22 ssh2\n"
            )
        f.flush()

    got_violation.wait(timeout=3)
    watcher.stop()

    assert len(violations) >= 1
    v = violations[0]
    assert v["violation_type"] == "failed_logins"
    assert v["username"] == "bruteman"
    assert "likelihood" in v
    assert "impact" in v
    assert "risk_score" in v
    assert "severity" in v


def test_logwatcher_does_not_crash_if_file_missing(tmp_path, config):
    auth_log = str(tmp_path / "missing_auth.log")
    web_log = str(tmp_path / "missing_web.log")

    watcher = LogWatcher(config)
    watcher.start(auth_log, web_log, lambda v: None)

    time.sleep(0.3)

    # Both threads should still be alive — no crash
    assert all(t.is_alive() for t in watcher._threads)

    watcher.stop()


def test_alert_flood_suppressed_within_window(config):
    """20 consecutive FAILED events for one user emit exactly ONE violation.

    Drives _check_failed_logins directly (no threads) for determinism: the
    cooldown must swallow every emission after the first within the window.
    """
    from datetime import datetime, timedelta

    cfg = {**config, "detection": {**config["detection"],
           "failed_logins": {"threshold": 5, "time_window_minutes": 10}}}
    watcher = LogWatcher(cfg)

    base = datetime(2026, 5, 27, 10, 0, 0)
    emitted = []
    for i in range(20):
        event = {
            "timestamp": base + timedelta(seconds=i),
            "username": "flooduser",
            "source_ip": "10.0.0.1",
            "source_host": "host-1",
            "resource": None,
            "status_code": "FAILED",
        }
        emitted.extend(watcher._check_failed_logins(event))

    assert len(emitted) == 1


def test_alert_emitted_again_after_window_expires(config):
    """A second burst after the window expires produces a second violation."""
    from datetime import datetime, timedelta

    cfg = {**config, "detection": {**config["detection"],
           "failed_logins": {"threshold": 5, "time_window_minutes": 10}}}
    watcher = LogWatcher(cfg)

    emitted = []

    def _burst(start: "datetime") -> None:
        for i in range(8):
            event = {
                "timestamp": start + timedelta(seconds=i),
                "username": "repeatuser",
                "source_ip": "10.0.0.1",
                "source_host": "host-1",
                "resource": None,
                "status_code": "FAILED",
            }
            emitted.extend(watcher._check_failed_logins(event))

    first_burst = datetime(2026, 5, 27, 10, 0, 0)
    _burst(first_burst)
    _burst(first_burst + timedelta(minutes=15))   # past the 10-min window

    assert len(emitted) == 2


def test_logwatcher_on_violation_called_within_2s(tmp_path, config):
    auth_log = tmp_path / "auth.log"
    web_log = tmp_path / "web.log"
    auth_log.touch()
    web_log.touch()

    got_violation = threading.Event()

    watcher = LogWatcher(config)
    watcher.start(str(auth_log), str(web_log), lambda v: got_violation.set())
    time.sleep(0.2)

    write_time = time.monotonic()
    with open(str(auth_log), "a") as f:
        for i in range(6):
            f.write(
                f"May 28 11:00:{i:02d} server sshd[1234]: "
                f"Failed password for speedtest from 10.0.0.2 port 22 ssh2\n"
            )
        f.flush()

    assert got_violation.wait(timeout=2), "on_violation not called within 2 seconds"
    elapsed = time.monotonic() - write_time
    assert elapsed < 2.0

    watcher.stop()


# ---------------------------------------------------------------------------
# Windows OpenSSH format end-to-end (guards against the silent-swallow trap):
# these exercise tail -> parser -> normalize_event -> detection -> on_violation.
# ---------------------------------------------------------------------------

def test_logwatcher_detects_windows_failed_login_burst(tmp_path, config):
    auth_log = tmp_path / "auth.log"
    web_log = tmp_path / "web.log"
    auth_log.touch()
    web_log.touch()

    violations = []
    got_violation = threading.Event()

    def on_violation(v):
        violations.append(v)
        got_violation.set()

    watcher = LogWatcher(config)
    watcher.start(str(auth_log), str(web_log), on_violation)
    time.sleep(0.2)

    # Windows OpenSSH file-log format: "<pid> <ISO ts> <message>".
    with open(str(auth_log), "a") as f:
        for i in range(6):
            f.write(
                f"6376 2026-08-16 03:17:{28 + i:02d}.251 "
                f"Failed password for winbrute from ::1 port 51785 ssh2\n"
            )
        f.flush()

    got_violation.wait(timeout=3)
    watcher.stop()

    assert len(violations) >= 1
    assert violations[0]["violation_type"] == "failed_logins"
    assert violations[0]["username"] == "winbrute"


def test_logwatcher_detects_windows_off_hours_login(tmp_path, config):
    auth_log = tmp_path / "auth.log"
    web_log = tmp_path / "web.log"
    auth_log.touch()
    web_log.touch()

    violations = []
    got_violation = threading.Event()

    def on_violation(v):
        violations.append(v)
        got_violation.set()

    watcher = LogWatcher(config)
    watcher.start(str(auth_log), str(web_log), on_violation)
    time.sleep(0.2)

    # Windows-format success login at 03:17 — outside business hours.
    with open(str(auth_log), "a") as f:
        f.write(
            "6376 2026-08-16 03:17:28.251 "
            "Accepted password for winuser from 10.0.0.9 port 51790 ssh2\n"
        )
        f.flush()

    got_violation.wait(timeout=3)
    watcher.stop()

    assert any(
        v["violation_type"] == "off_hours_login" and v["username"] == "winuser"
        for v in violations
    )
