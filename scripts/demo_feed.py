"""Presentation-only demo feeder.

Continuously replays REAL historical log lines into the live-monitored log files
so the running app's Live Feed and Trend panels show active detection during a
supervisor / marker demo. Run it in a second terminal alongside `python main.py`.

This tool touches NONE of the detection, scoring, or storage logic. It only:
  1. reads lines from the real LogHub datasets (READ-ONLY),
  2. rewrites the timestamp portion of each line to the current system time,
     keeping every other field (user, IP, status code, resource) untouched, and
  3. appends the rewritten line to whichever log files the app is tailing.

SAFETY: logs/real/ is evaluation evidence and must never change. Source files
are opened READ-ONLY (mode "r"). This script never opens a source path for
writing, and asserts at startup that no destination path resolves inside
logs/real/. File hashes of the sources are identical before and after a run.

Destinations are the live-monitored files logs/live/auth.log and
logs/live/access.log. Point the app at these (config.yaml auth_log_path /
web_log_path) so LogWatcher tails them while the demo runs.

Usage:
    python scripts/demo_feed.py        # Ctrl+C to stop
"""
import os
import random
import re
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DIR = os.path.join(ROOT, "logs", "real")

# Fixed live-monitored destinations. Deliberately NOT derived from config: the
# demo must always write to logs/live/, never wherever config happens to point
# (which could be the read-only logs/real/ evidence).
AUTH_DEST = os.path.join(ROOT, "logs", "live", "auth.log")
WEB_DEST = os.path.join(ROOT, "logs", "live", "access.log")


# ---------------------------------------------------------------------------
# Timestamp rewriters — one per real-world format. Each replaces ONLY the
# timestamp and leaves the rest of the line byte-for-byte intact.
# ---------------------------------------------------------------------------

_SYSLOG_RE = re.compile(r"^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}")
_APACHE_COMBINED_RE = re.compile(
    r"\[\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2}\s([+-]\d{4})\]"
)
_APACHE_ERROR_RE = re.compile(
    r"\[[A-Za-z]{3}\s[A-Za-z]{3}\s\d{2}\s\d{2}:\d{2}:\d{2}\s\d{4}\]"
)


def _rewrite_syslog(line: str, now: datetime) -> str:
    # "Aug 28 09:59:16 ..." — month, space-padded day, time (no year)
    new_ts = f"{now.strftime('%b')} {now.day:2d} {now.strftime('%H:%M:%S')}"
    return _SYSLOG_RE.sub(new_ts, line, count=1)


def _rewrite_apache_combined(line: str, now: datetime) -> str:
    # "[28/Aug/2005:05:07:44 -0400]" — keep the original UTC offset
    def repl(m: "re.Match") -> str:
        return f"[{now.strftime('%d/%b/%Y:%H:%M:%S')} {m.group(1)}]"
    return _APACHE_COMBINED_RE.sub(repl, line, count=1)


def _rewrite_apache_error(line: str, now: datetime) -> str:
    # "[Sun Dec 04 04:47:44 2005]" — weekday, month, zero-padded day, time, year
    new_ts = f"[{now.strftime('%a %b %d %H:%M:%S %Y')}]"
    return _APACHE_ERROR_RE.sub(new_ts, line, count=1)


# ---------------------------------------------------------------------------
# Sources — cycled round-robin, one line each. dest is "auth" or "web".
# ---------------------------------------------------------------------------

SOURCES = [
    {"name": "secure",        "file": "secure",        "rewrite": _rewrite_syslog,          "dest": "auth"},
    {"name": "access_log",    "file": "access_log",    "rewrite": _rewrite_apache_combined, "dest": "web"},
    {"name": "Apache_2k.log", "file": "Apache_2k.log", "rewrite": _rewrite_apache_error,    "dest": "web"},
    {"name": "SSH_2k.log",    "file": "SSH_2k.log",    "rewrite": _rewrite_syslog,          "dest": "auth"},
]


def _assert_not_in_real(path: str) -> None:
    """Guard: a destination must never resolve inside logs/real/."""
    real = os.path.abspath(REAL_DIR)
    if os.path.abspath(path).startswith(real):
        raise SystemExit(f"[demo] refusing to write inside logs/real/: {path}")


def _load_source_lines() -> list:
    """Read each source file READ-ONLY into memory. logs/real/ is never written."""
    loaded = []
    for src in SOURCES:
        path = os.path.join(REAL_DIR, src["file"])
        if not os.path.exists(path):
            print(f"[demo] WARNING: source not found, skipping: {path}")
            continue
        # Mode "r" ONLY — this is the sole access to evaluation evidence.
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
        if lines:
            loaded.append({**src, "lines": lines, "pos": 0})
    return loaded


def main() -> int:
    _assert_not_in_real(AUTH_DEST)
    _assert_not_in_real(WEB_DEST)
    os.makedirs(os.path.dirname(AUTH_DEST), exist_ok=True)
    os.makedirs(os.path.dirname(WEB_DEST), exist_ok=True)
    dest_for = {"auth": AUTH_DEST, "web": WEB_DEST}

    sources = _load_source_lines()
    if not sources:
        print("[demo] no source files found under logs/real/ — nothing to feed.")
        return 1

    print("CyberMon demo feeder — replaying real log lines with current timestamps.")
    print(f"  auth lines -> {os.path.relpath(AUTH_DEST, ROOT)}")
    print(f"  web  lines -> {os.path.relpath(WEB_DEST, ROOT)}")
    print("  Start this AFTER 'python main.py' is running. Press Ctrl+C to stop.\n")

    fed = 0
    si = 0
    try:
        while True:
            src = sources[si % len(sources)]
            si += 1

            line = src["lines"][src["pos"] % len(src["lines"])]
            src["pos"] += 1

            rewritten = src["rewrite"](line, datetime.now())
            dest = dest_for[src["dest"]]
            with open(dest, "a", encoding="utf-8") as fh:
                fh.write(rewritten + "\n")

            fed += 1
            print(f"[demo] fed line from {src['name']} -> {os.path.relpath(dest, ROOT)}")
            time.sleep(random.uniform(2.0, 4.0))
    except KeyboardInterrupt:
        print(f"\n[demo] stopped. Fed {fed} line(s). logs/real/ untouched.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
