import logging
import threading
import time
from collections import deque
from datetime import timedelta

from src.ingestion.parser import parse_auth_log_line, parse_access_log_line
from src.ingestion.preprocessor import normalize_event
from src.detection.rules.unauthorized_access import detect_unauthorized_access
from src.detection.rules.off_hours import detect_off_hours_logins
from src.scoring.scorer import score_violation


def tail_file(
    filepath: str,
    log_type: str,
    callback,
    poll_interval: float = 0.5,
    stop_event: threading.Event | None = None,
) -> None:
    """Tail filepath, calling callback(line, log_type) for each new line.

    Seeks to the end on open so only lines written after this call is made
    are delivered. Retries silently if the file is temporarily missing or
    unreadable. Runs until stop_event is set (or forever if None is passed,
    in which case the caller must use a daemon thread).
    """
    def _should_stop() -> bool:
        return stop_event is not None and stop_event.is_set()

    while not _should_stop():
        try:
            with open(filepath, "r") as f:
                f.seek(0, 2)  # skip any existing content
                while not _should_stop():
                    line = f.readline()
                    if line:
                        callback(line.rstrip("\n"), log_type)
                    else:
                        time.sleep(poll_interval)
        except FileNotFoundError:
            logging.warning("tail_file: %s not found, retrying in %.1fs", filepath, poll_interval)
            time.sleep(poll_interval)
        except Exception as exc:
            logging.warning("tail_file: error on %s: %s", filepath, exc)
            time.sleep(poll_interval)


class LogWatcher:
    """Tails auth and web log files, running the full detection + scoring
    pipeline on each new line and calling on_violation for every hit."""

    def __init__(self, config: dict) -> None:
        self._config = config
        self._stop = threading.Event()
        self._failed_buffer: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    def start(self, auth_log: str, web_log: str, on_violation) -> None:
        self._stop.clear()
        self._threads = []
        cb = self._make_callback(on_violation)
        for filepath, log_type in ((auth_log, "auth"), (web_log, "web")):
            t = threading.Thread(
                target=tail_file,
                args=(filepath, log_type, cb, 0.5, self._stop),
                daemon=True,
            )
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()

    def _make_callback(self, on_violation):
        def callback(line: str, log_type: str) -> None:
            self._handle(line, log_type, on_violation)
        return callback

    def _handle(self, line: str, log_type: str, on_violation) -> None:
        parser = parse_auth_log_line if log_type == "auth" else parse_access_log_line
        parsed = parser(line)
        if parsed is None:
            return

        event = normalize_event(parsed, log_type)
        violations = []

        if log_type == "auth" and event["status_code"] == "FAILED":
            violations.extend(self._check_failed_logins(event))

        if log_type == "auth" and event["status_code"] == "SUCCESS":
            violations.extend(detect_off_hours_logins([event], self._config))

        if log_type == "web":
            violations.extend(detect_unauthorized_access([event], self._config))

        for v in violations:
            on_violation(score_violation(v, self._config))

    def _check_failed_logins(self, event: dict) -> list[dict]:
        cfg = self._config["detection"]["failed_logins"]
        threshold = cfg["threshold"]
        window = timedelta(minutes=cfg["time_window_minutes"])
        username = event["username"]
        ts = event["timestamp"]

        with self._lock:
            buf = self._failed_buffer.setdefault(username, deque())
            buf.append(ts)
            while buf and ts - buf[0] > window:
                buf.popleft()
            count = len(buf)

        if count > threshold:
            return [{
                "violation_type": "failed_logins",
                "timestamp": ts,
                "username": username,
                "source_ip": event["source_ip"],
                "resource": event["resource"],
                "detail": (
                    f"{count} failed logins in "
                    f"{int(window.total_seconds() // 60)} minutes"
                ),
            }]
        return []
