import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta

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
                        stripped = line.rstrip("\n")
                        # Isolate per-line handling: one malformed line must not
                        # break the read loop (which would reopen + re-seek to
                        # end, dropping the tail position and intervening lines).
                        try:
                            callback(stripped, log_type)
                        except Exception as exc:
                            logging.warning(
                                "tail_file: skipping unprocessable line in %s: %r (%s)",
                                filepath, stripped, exc,
                            )
                    else:
                        time.sleep(poll_interval)
        except FileNotFoundError:
            logging.warning("tail_file: %s not found, retrying in %.1fs", filepath, poll_interval)
            time.sleep(poll_interval)
        except PermissionError:
            logging.error(
                "tail_file: permission denied reading %s — is CyberMon running "
                "as Administrator?", filepath,
            )
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
        # Keyed by "source_host:username" so the same username on two hosts
        # is never pooled into one count.
        self._failed_buffer: dict[str, deque] = {}
        # Last violation emission time per key — suppresses alert flooding:
        # a 100-attempt brute force is one violation, not ~98.
        self._violation_cooldown: dict[str, datetime] = {}
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    def start(self, auth_log: str, web_log: str, on_violation, on_event=None) -> None:
        """Tail both logs, emitting violations via on_violation.

        on_event is an optional event sink called with each normalized event
        BEFORE detection runs. It exists so the caller can persist the event
        (and its raw_log) first, guaranteeing the row a violation's
        triggering_event_id points at already exists. Persistence is injected:
        this module never imports the storage layer.
        """
        self._stop.clear()
        self._threads = []
        cb = self._make_callback(on_violation, on_event)
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

    def _make_callback(self, on_violation, on_event=None):
        def callback(line: str, log_type: str) -> None:
            self._handle(line, log_type, on_violation, on_event)
        return callback

    def _handle(self, line: str, log_type: str, on_violation, on_event=None) -> None:
        parser = parse_auth_log_line if log_type == "auth" else parse_access_log_line
        parsed = parser(line)
        if parsed is None:
            return

        event = normalize_event(parsed, log_type)

        # Hand the event to the sink (if any) before detection, so a violation
        # emitted below can resolve its triggering_event_id against a row that
        # already exists.
        if on_event is not None:
            on_event(event)

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
        source_host = event.get("source_host", "")
        ts = event["timestamp"]
        key = f"{source_host}:{username}"

        with self._lock:
            buf = self._failed_buffer.setdefault(key, deque())
            buf.append(ts)
            while buf and ts - buf[0] > window:
                buf.popleft()
            count = len(buf)

            if count > threshold:
                last_emitted = self._violation_cooldown.get(key)
                if last_emitted and ts - last_emitted < window:
                    return []   # already reported this burst; suppress duplicate
                self._violation_cooldown[key] = ts
                return [{
                    "violation_type": "failed_logins",
                    "timestamp": ts,
                    "username": username,
                    "source_host": source_host,
                    "source_ip": event.get("source_ip"),
                    "resource": None,
                    "detail": (
                        f"{count} failed logins in "
                        f"{cfg['time_window_minutes']} min for user '{username}'"
                    ),
                }]
        return []
