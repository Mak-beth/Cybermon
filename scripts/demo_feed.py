"""Presentation-only demo feeder (demo-optimized).

Continuously replays REAL historical log lines into the live-monitored log files
so the running app's Live Feed and Trend panels show active detection during a
supervisor / marker demo. Run it in a second terminal alongside `python main.py`.

Two demo optimizations over raw random sampling:

  * 70/30 violation bias — each source is split at startup into a "violation"
    pool (lines matching current detection rules) and a "normal" pool, and picks
    are weighted 70/30 toward violations.

  * Per-user bursts (failed logins) — the real anti-flood cooldown in the watcher
    (keyed on source_host:username, 10-min window) fires ONE violation per user
    per window. Because this feeder stamps every line "now", a single username
    would fire once and then be suppressed for the whole session. So the auth
    violation pool is grouped by username and fed in short bursts (threshold+1
    lines) that ROTATE across distinct users — each burst is a fresh
    source_host:username key and therefore a genuinely distinct, non-suppressed
    violation. The cooldown itself is never touched.

This tool touches NONE of the detection, scoring, or storage logic. It only:
  1. reads lines from the real LogHub datasets (READ-ONLY),
  2. rewrites the timestamp portion of each line to the current system time,
     keeping every other field (user, IP, status code, resource) untouched, and
  3. appends the rewritten line to the live-monitored log files.

SAFETY: logs/real/ is evaluation evidence and must never change. Source files
are opened READ-ONLY (mode "r"/"rb"). This script never opens a source path for
writing, asserts at startup that no destination resolves inside logs/real/, and
verifies the SHA-256 of every source file is byte-identical before and after a run.

Destinations are the live-monitored files logs/live/auth.log and
logs/live/access.log. Point the app at these (config.yaml auth_log_path /
web_log_path) so LogWatcher tails them while the demo runs.

Usage:
    python scripts/demo_feed.py                 # Ctrl+C to stop
    python scripts/demo_feed.py --seconds 60    # bounded run (same clean summary)
"""
import argparse
import hashlib
import os
import random
import re
import sys
import time
from collections import deque
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DIR = os.path.join(ROOT, "logs", "real")
# Hand-written demo inputs (labelled, not evidence) — see logs/demo/README.md.
DEMO_DIR = os.path.join(ROOT, "logs", "demo")

# Make `import src...` work when run as `python scripts/demo_feed.py`.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import yaml
from src.ingestion.parser import parse_auth_log_line, parse_access_log_line
from src.ingestion.preprocessor import normalize_event
from src.detection.rules.unauthorized_access import detect_unauthorized_access

# Fixed live-monitored destinations. Deliberately NOT derived from config: the
# demo must always write to logs/live/, never wherever config happens to point
# (which could be the read-only logs/real/ evidence).
AUTH_DEST = os.path.join(ROOT, "logs", "live", "auth.log")
WEB_DEST = os.path.join(ROOT, "logs", "live", "access.log")

# Fraction of picks drawn from a source's violation pool (when it has one).
VIOLATION_BIAS = 0.70
# How many recently-burst usernames to avoid reusing (shared across auth sources,
# so secure and SSH_2k.log don't fire the same source_host:username key).
RECENT_USERS = 12


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


def _rewrite_offhours(line: str, now: datetime) -> str:
    """Syslog rewrite that stamps TODAY at an off-hours time in the past, so a
    successful login reliably trips off_hours_login whenever the demo runs.

    off_hours fires for any time outside 08:00-18:00. During business hours we
    use 03:xx today (off-hours and already elapsed); outside them, "now" already
    qualifies. Either way the date is today, so it lands in the trend window.
    """
    stamp = now.replace(hour=3) if 8 <= now.hour < 18 else now
    new_ts = f"{stamp.strftime('%b')} {stamp.day:2d} {stamp.strftime('%H:%M:%S')}"
    return _SYSLOG_RE.sub(new_ts, line, count=1)


# ---------------------------------------------------------------------------
# Sources — cycled round-robin, one line each.
#   dest: "auth" | "web"        — which live file the rewritten line is appended to
#   kind: "failed" | "unauth" | "offhours"
#         failed   -> per-user burst rotation (defeats the failed-login cooldown)
#         unauth   -> each violation line trips unauthorized_access (no cooldown)
#         offhours -> each violation line trips off_hours_login (no cooldown)
#   dir:  REAL_DIR (evidence, hash-guarded) or DEMO_DIR (labelled demo input)
# ---------------------------------------------------------------------------

SOURCES = [
    {"name": "secure",        "file": "secure",          "dir": REAL_DIR, "rewrite": _rewrite_syslog,          "dest": "auth", "kind": "failed"},
    {"name": "access_log",    "file": "access_log",      "dir": REAL_DIR, "rewrite": _rewrite_apache_combined, "dest": "web",  "kind": "unauth"},
    {"name": "Apache_2k.log", "file": "Apache_2k.log",   "dir": REAL_DIR, "rewrite": _rewrite_apache_error,    "dest": "web",  "kind": "unauth"},
    {"name": "SSH_2k.log",    "file": "SSH_2k.log",      "dir": REAL_DIR, "rewrite": _rewrite_syslog,          "dest": "auth", "kind": "failed"},
    {"name": "access_demo",   "file": "access_demo.log", "dir": DEMO_DIR, "rewrite": _rewrite_apache_combined, "dest": "web",  "kind": "unauth"},
    {"name": "auth_demo",     "file": "auth_demo.log",   "dir": DEMO_DIR, "rewrite": _rewrite_offhours,        "dest": "auth", "kind": "offhours"},
]


def _source_path(src: dict) -> str:
    return os.path.join(src.get("dir", REAL_DIR), src["file"])


def _load_config() -> dict:
    with open(os.path.join(ROOT, "config", "config.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _web_is_violation(line: str, config: dict) -> bool:
    """True if a web line is a 403/401 on a restricted resource (live config)."""
    parsed = parse_access_log_line(line)
    if parsed is None:
        return False
    event = normalize_event(parsed, "web")
    return len(detect_unauthorized_access([event], config)) > 0


def _auth_failed_user(line: str):
    """Return the username of a failed-login auth line, else None (READ-ONLY)."""
    parsed = parse_auth_log_line(line)
    if parsed is None or parsed.get("status") != "failure":
        return None
    return parsed.get("username")


def _auth_is_success(line: str) -> bool:
    """True if the line is a successful auth login (trips off_hours when off-hours)."""
    parsed = parse_auth_log_line(line)
    return parsed is not None and parsed.get("status") == "success"


def _assert_not_in_real(path: str) -> None:
    """Guard: a destination must never resolve inside logs/real/."""
    real = os.path.abspath(REAL_DIR)
    if os.path.abspath(path).startswith(real):
        raise SystemExit(f"[demo] refusing to write inside logs/real/: {path}")


def _source_hashes() -> dict:
    """SHA-256 of every logs/real/ source (READ-ONLY) — the evidence integrity
    guard. Demo inputs under logs/demo/ are not evidence and are not covered."""
    hashes = {}
    for src in SOURCES:
        if src.get("dir", REAL_DIR) != REAL_DIR:
            continue
        path = _source_path(src)
        if os.path.exists(path):
            with open(path, "rb") as fh:      # "rb" — read only, never written
                hashes[src["file"]] = hashlib.sha256(fh.read()).hexdigest()
    return hashes


def _build_pools(config: dict) -> list:
    """Read each source READ-ONLY once and split into violation / normal pools.

    Auth sources also get their violation pool grouped by username (by_user) plus
    a shuffled rotation queue, so failed logins can be fed as per-user bursts.
    """
    loaded = []
    for src in SOURCES:
        path = _source_path(src)
        if not os.path.exists(path):
            print(f"[demo] WARNING: source not found, skipping: {path}")
            continue
        # Mode "r" ONLY — the sole textual access to source files.
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
        if not lines:
            continue

        violation, normal = [], []
        by_user: dict = {}
        for ln in lines:
            if src["kind"] == "failed":
                user = _auth_failed_user(ln)
                if user is not None:
                    violation.append(ln)
                    by_user.setdefault(user, []).append(ln)
                else:
                    normal.append(ln)
            elif src["kind"] == "offhours":
                (violation if _auth_is_success(ln) else normal).append(ln)
            else:  # unauth
                (violation if _web_is_violation(ln, config) else normal).append(ln)

        entry = {**src, "violation": violation, "normal": normal}
        if src["kind"] == "failed":
            entry["by_user"] = by_user
        loaded.append(entry)
    return loaded


def _next_burst_line(burst: dict, by_user: dict, queue: deque,
                     burst_size: int, recent_users: deque):
    """Return the next failed-login line for the current per-user burst, starting
    a fresh burst on a new (preferably not-recently-used) username when needed.

    Shared across both auth sources so a username fires once, not once per source.
    """
    if burst["remaining"] <= 0:
        chosen = None
        for _ in range(len(queue)):    # rotate the queue looking for a fresh user
            u = queue[0]
            queue.rotate(-1)           # move front to back (LRU)
            if u not in recent_users:
                chosen = u
                break
        if chosen is None:             # every user recently used — take the front
            chosen = queue[0]
            queue.rotate(-1)
        recent_users.append(chosen)
        burst.update(user=chosen, pool=by_user[chosen], idx=0, remaining=burst_size)

    line = burst["pool"][burst["idx"] % len(burst["pool"])]
    burst["idx"] += 1
    burst["remaining"] -= 1
    return line, burst["user"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Demo feeder — replay real logs into logs/live with a 70/30 "
                    "violation bias and rotating per-user failed-login bursts."
    )
    parser.add_argument(
        "--seconds", type=float, default=None,
        help="Optional: stop after N seconds via the same clean summary (default: run until Ctrl+C).",
    )
    args = parser.parse_args()

    _assert_not_in_real(AUTH_DEST)
    _assert_not_in_real(WEB_DEST)
    os.makedirs(os.path.dirname(AUTH_DEST), exist_ok=True)
    os.makedirs(os.path.dirname(WEB_DEST), exist_ok=True)
    dest_for = {"auth": AUTH_DEST, "web": WEB_DEST}

    config = _load_config()
    # Watcher fires when count > threshold, so a burst of threshold+1 same-user
    # failures guarantees exactly one fresh violation per rotated username.
    threshold = config.get("detection", {}).get("failed_logins", {}).get("threshold", 2)
    burst_size = threshold + 1

    before_hashes = _source_hashes()      # integrity baseline
    sources = _build_pools(config)
    if not sources:
        print("[demo] no source files found under logs/real/ — nothing to feed.")
        return 1

    # Merge every auth source's failed-login lines into one username->lines map so
    # the burst rotation cycles the combined user set (secure + SSH_2k.log) and a
    # user fires once overall, not once per source.
    auth_by_user: dict = {}
    for src in sources:
        for user, lns in src.get("by_user", {}).items():
            auth_by_user.setdefault(user, []).extend(lns)
    auth_users = list(auth_by_user.keys())
    random.shuffle(auth_users)
    auth_queue: deque = deque(auth_users)
    burst = {"user": None, "pool": [], "idx": 0, "remaining": 0}

    print("CyberMon demo feeder — replaying real log lines with current timestamps.")
    print(f"  auth lines -> {os.path.relpath(AUTH_DEST, ROOT)}")
    print(f"  web  lines -> {os.path.relpath(WEB_DEST, ROOT)}")
    for src in sources:
        extra = f", {len(src['by_user'])} distinct users" if src["kind"] == "failed" else ""
        print(f"[demo] {src['name']} [{src['kind']}]: {len(src['violation'])} violation-pool "
              f"/ {len(src['normal'])} normal-pool lines loaded{extra}")
    print(f"[demo] failed-login users (merged across auth sources): {len(auth_by_user)}; "
          f"burst size = {burst_size} (threshold {threshold} + 1), rotating across users.")
    print("  Start this AFTER 'python main.py' is running. Press Ctrl+C to stop.\n")

    fed = fed_violation = fed_normal = 0
    si = 0
    recent_users: deque = deque(maxlen=RECENT_USERS)
    deadline = (time.monotonic() + args.seconds) if args.seconds else None

    def _summary(reason: str) -> int:
        after_hashes = _source_hashes()
        unchanged = after_hashes == before_hashes
        print(f"\n[demo] {reason}. Fed {fed} line(s): "
              f"{fed_violation} violation-pool, {fed_normal} normal-pool.")
        print(f"[demo] logs/real/ source hashes "
              f"{'UNCHANGED — verified byte-identical.' if unchanged else 'CHANGED — WARNING!'}")
        return 0 if unchanged else 1

    try:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                return _summary("time limit reached")

            src = sources[si % len(sources)]      # round-robin across sources (unchanged)
            si += 1

            burst_user = None
            if src["kind"] == "failed" and auth_by_user:
                # Failed logins: 70% a rotating per-user burst (defeats the
                # cooldown by using a fresh source_host:username each burst),
                # 30% normal traffic.
                if random.random() < VIOLATION_BIAS:
                    line, burst_user = _next_burst_line(
                        burst, auth_by_user, auth_queue, burst_size, recent_users)
                    use_violation = True
                else:
                    line = random.choice(src["normal"]) if src["normal"] else \
                        _next_burst_line(
                            burst, auth_by_user, auth_queue, burst_size, recent_users)[0]
                    use_violation = not src["normal"]
            else:
                # unauth / offhours (and empty-pool sources): 70/30 flat sampling,
                # 100% normal when the violation pool is empty. These rules have
                # no cooldown, so each fed violation line trips one detection.
                use_violation = bool(src["violation"]) and random.random() < VIOLATION_BIAS
                pool = src["violation"] if use_violation else src["normal"]
                if not pool:
                    pool = src["violation"] or src["normal"]
                    use_violation = pool is src["violation"]
                line = random.choice(pool)

            rewritten = src["rewrite"](line, datetime.now())
            dest = dest_for[src["dest"]]
            with open(dest, "a", encoding="utf-8") as fh:
                fh.write(rewritten + "\n")

            fed += 1
            if use_violation:
                fed_violation += 1
            else:
                fed_normal += 1
            tag = "VIOLATION" if use_violation else "normal   "
            who = f" (user={burst_user})" if burst_user else ""
            print(f"[demo] fed {tag} from {src['name']:13} -> "
                  f"{os.path.relpath(dest, ROOT)}{who}")

            time.sleep(random.uniform(0.5, 1.0))
    except KeyboardInterrupt:
        return _summary("stopped")


if __name__ == "__main__":
    sys.exit(main())
