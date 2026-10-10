"""Live log monitoring controller.

Owns the running app's LogWatcher together with the two database callbacks it
feeds, so the GUI can switch log files mid-session without a restart.

Forward-only by design: restart() tails the new files from their current end.
It never re-runs run_pipeline() or _prepare_database(). Those are startup-only,
because running them mid-session would wipe data, duplicate rows and freeze
the UI. Lines already in the new files are not analysed.

Qt-free, so it can be tested headless. The watcher module stays storage-free:
persistence is injected from here.
"""
from __future__ import annotations

import logging
import os
import threading

from src.ingestion import watcher as _watcher
from src.storage.writer import (
    find_triggering_event_id,
    insert_events,
    insert_risk_score,
    insert_violation,
)

logger = logging.getLogger(__name__)

# How long restart() and stop() wait for the old tail threads to exit. A tail
# thread notices stop within one poll interval (0.5 s), plus any in-flight write.
JOIN_TIMEOUT_SECONDS = 2.0


def missing_log_paths(auth_log: str, web_log: str) -> list[str]:
    """Return the given paths that are empty or not an existing regular file."""
    return [path for path in (auth_log, web_log) if not path or not os.path.isfile(path)]


class LiveMonitor:
    """Starts, restarts and stops live tailing of the auth and web logs."""

    def __init__(self, config: dict, db_path: str) -> None:
        self._config = config
        self._db_path = db_path
        # Looked up on the module at construction time, so tests can patch
        # src.ingestion.watcher.LogWatcher.
        self._watcher = _watcher.LogWatcher(config)
        # Serialises start/restart/stop.
        self._lock = threading.Lock()
        self.auth_log: str | None = None
        self.web_log: str | None = None

    @property
    def db_path(self) -> str:
        return self._db_path

    def start(self, auth_log: str, web_log: str) -> None:
        """Begin tailing both logs. Used once at startup.

        Paths are not validated here: as before, a tail thread keeps retrying a
        file that does not exist yet, and MainWindow's startup banner reports it.
        """
        with self._lock:
            self._start_locked(auth_log, web_log)

    def restart(self, auth_log: str, web_log: str) -> list[str]:
        """Switch live monitoring to new log files.

        Validates first. If either path is missing, nothing is stopped or
        started, and the missing paths are returned so the caller can warn;
        the previous files stay monitored. Otherwise: stop the watcher, wait
        for both tail threads to exit, clear failed-login state, start on the
        new paths, and return [].
        """
        missing = missing_log_paths(auth_log, web_log)
        if missing:
            logger.warning("live monitor: not restarting, log file(s) not found: %s", missing)
            return missing
        with self._lock:
            self._stop_locked(JOIN_TIMEOUT_SECONDS)
            self._watcher.reset_state()
            self._start_locked(auth_log, web_log)
        return []

    def stop(self, timeout: float = JOIN_TIMEOUT_SECONDS) -> bool:
        """Stop tailing and wait for the threads. True if they all exited."""
        with self._lock:
            return self._stop_locked(timeout)

    # ------------------------------------------------------------------

    def _start_locked(self, auth_log: str, web_log: str) -> None:
        self._watcher.start(
            auth_log=auth_log,
            web_log=web_log,
            on_violation=self._on_violation,
            on_event=self._on_event,
        )
        self.auth_log, self.web_log = auth_log, web_log

    def _stop_locked(self, timeout: float) -> bool:
        self._watcher.stop()
        exited = self._watcher.join(timeout)
        if not exited:
            # Safe to carry on: each run has its own stop Event, so a slow old
            # thread still exits once its current line is handled.
            logger.warning(
                "live monitor: tail thread(s) still running after %.1fs; "
                "they will exit after their current line", timeout)
        return exited

    # ------------------------------------------------------------------
    # Database callbacks (run on the tail threads)
    # ------------------------------------------------------------------

    def _on_event(self, event: dict) -> None:
        """Persist each live event exactly like the batch pipeline does.

        Runs before detection, so a violation's triggering_event_id resolves to
        a real row and the detail view can show the raw log excerpt.

        Note: live mode runs continuously, so the events table grows for as long
        as the app is running. That is accepted here; there is deliberately no
        retention/pruning logic.
        """
        try:
            insert_events([event], self._db_path)
        except Exception as exc:
            logger.error("Live event sink error: %s", exc)

    def _on_violation(self, scored_violation: dict) -> None:
        try:
            scored_violation["triggering_event_id"] = find_triggering_event_id(
                scored_violation, self._db_path
            )
            vid = insert_violation(scored_violation, self._db_path)
            insert_risk_score(vid, scored_violation, self._db_path)
        except Exception as exc:
            logger.error("Live callback error: %s", exc)
