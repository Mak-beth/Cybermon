"""CyberMon Agent — tails a log file and POSTs new lines to the ingest endpoint.

Dependencies: Python standard library + requests only.
"""
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)


class CyberMonAgent:
    """Continuously tails a log file and POSTs batches of new lines to the server."""

    def __init__(
        self,
        server_ip: str,
        server_port: int,
        log_path: str,
        host_id: str,
        api_key: str = "",
        retry_attempts: int = 3,
        retry_delay_seconds: int = 2,
    ) -> None:
        self.url = f"http://{server_ip}:{server_port}/ingest"
        self.log_path = log_path
        self.host_id = host_id
        self.api_key = api_key
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay_seconds
        self._running = False

    # ------------------------------------------------------------------
    # POST helpers
    # ------------------------------------------------------------------

    def _post_lines(self, lines: list) -> bool:
        """POST lines to the ingest endpoint.  Returns True on success."""
        payload = {"host": self.host_id, "lines": lines}
        headers = {"X-API-Key": self.api_key, "Content-Type": "application/json"}
        for attempt in range(1, self.retry_attempts + 1):
            try:
                resp = requests.post(self.url, json=payload, headers=headers, timeout=5)
                if resp.status_code == 200:
                    logger.info(
                        "Sent %d line(s) to %s — server: %s",
                        len(lines), self.url, resp.json(),
                    )
                    print(f"[CyberMonAgent] Sent {len(lines)} line(s) — {resp.json()}")
                    return True
                if resp.status_code == 401:
                    logger.error("Server rejected API key (HTTP 401) — not retrying.")
                    print(
                        "[CyberMonAgent] FATAL: server rejected API key. "
                        "Check that 'api_key' in agent_config.yaml matches the "
                        "server's server.api_key. Not retrying."
                    )
                    return False
                logger.warning(
                    "Server returned HTTP %d (attempt %d/%d)",
                    resp.status_code, attempt, self.retry_attempts,
                )
                print(f"[CyberMonAgent] Server returned {resp.status_code} — retrying…")
            except requests.RequestException as exc:
                logger.warning(
                    "POST failed (attempt %d/%d): %s",
                    attempt, self.retry_attempts, exc,
                )
                print(f"[CyberMonAgent] Connection error (attempt {attempt}/{self.retry_attempts}): {exc}")
            if attempt < self.retry_attempts:
                time.sleep(self.retry_delay)

        logger.error(
            "All %d POST attempts failed for %d line(s) — dropping batch.",
            self.retry_attempts, len(lines),
        )
        print(f"[CyberMonAgent] ERROR — all {self.retry_attempts} attempts failed; batch dropped.")
        return False

    # ------------------------------------------------------------------
    # Main tail loop
    # ------------------------------------------------------------------

    def run(self, poll_interval: float = 0.5) -> None:
        """Tail self.log_path indefinitely, POSTing new lines to the server.

        Seeks to the end of the file on open so only lines written *after*
        this call are delivered.  Handles missing files by retrying quietly.
        """
        self._running = True
        logger.info("Agent started. Watching %s -> %s", self.log_path, self.url)
        print(f"[CyberMonAgent] Watching {self.log_path}")
        print(f"[CyberMonAgent] Posting to {self.url} as host '{self.host_id}'")

        while self._running:
            if not os.path.exists(self.log_path):
                logger.warning(
                    "Log file not found: %s — retrying in %.1fs",
                    self.log_path, poll_interval,
                )
                time.sleep(poll_interval)
                continue

            try:
                with open(self.log_path, "r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(0, 2)  # jump to end; only new lines are sent
                    while self._running:
                        # Drain all lines currently available before sleeping
                        batch = []
                        while True:
                            line = fh.readline()
                            if line:
                                stripped = line.rstrip("\n")
                                if stripped:
                                    batch.append(stripped)
                            else:
                                break  # caught up
                        if batch:
                            self._post_lines(batch)
                        else:
                            time.sleep(poll_interval)
            except FileNotFoundError:
                logger.warning("Log file disappeared: %s", self.log_path)
                time.sleep(poll_interval)
            except Exception as exc:  # pragma: no cover
                logger.error("Unexpected error tailing %s: %s", self.log_path, exc)
                time.sleep(poll_interval)

    def stop(self) -> None:
        """Signal the run loop to exit on its next iteration."""
        self._running = False
        logger.info("Agent stop requested.")
