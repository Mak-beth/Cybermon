"""
Appends realistic log lines to the configured log files, producing violations
across all four severity tiers when the pipeline is run afterwards.

Log paths are read from config/config.yaml (auth_log_path, web_log_path) so
simulate.py always writes to the same files that main.py will process.
Falls back to logs/live/auth.log and logs/live/access.log if config is absent.

Run this script, then run `python main.py` to see all four tiers in the GUI.

Tier   | Pattern                          | L | I | Score
-------|----------------------------------|---|---|------
Low      3 failed logins for guest_HHMMSS 2   2    4
Medium   8 failed logins for hacker       3   2    6
High     3 x GET /admin -> 403            3   5   15
Critical 20 failed logins for admin       5   4   20

The Low-tier username carries a per-run suffix (guest_HHMMSS): detection takes
the MAX failure count in any window across the whole file, so two simulate runs
within 10 minutes of each other would otherwise merge into 6 failures for
'guest' and promote the violation to Medium — losing the Low tier entirely.
A unique username per run keeps the Low count at exactly 3.
The other tiers are immune: hacker doubling (16) stays Medium-banded via L=4,
admin is already Critical-capped, and /admin 403s score per event.
"""
import os
import time
from datetime import datetime

import yaml

# ---------------------------------------------------------------------------
# Resolve log paths from config — keeps simulate in sync with main.py
# ---------------------------------------------------------------------------
_AUTH_DEFAULT = "logs/live/auth.log"
_WEB_DEFAULT  = "logs/live/access.log"

try:
    _cfg = yaml.safe_load(open("config/config.yaml"))
    AUTH_LOG = _cfg.get("auth_log_path", _AUTH_DEFAULT)
    WEB_LOG  = _cfg.get("web_log_path",  _WEB_DEFAULT)
except Exception:
    AUTH_LOG = _AUTH_DEFAULT
    WEB_LOG  = _WEB_DEFAULT


def _auth_ts(now: datetime) -> str:
    return now.strftime("%b %d %H:%M:%S").replace(" 0", "  ")


def _web_ts(now: datetime) -> str:
    return now.strftime("%d/%b/%Y:%H:%M:%S +0000")


def append(filepath: str, line: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "a") as f:
        f.write(line + "\n")
    print(f"[+] {filepath}: {line}")


def main():
    print(f"Cybermon simulator starting.")
    print(f"  auth log : {AUTH_LOG}")
    print(f"  web log  : {WEB_LOG}\n")

    pid_base = 2000

    # Low (score 4): 3 failed logins for a per-run unique guest user
    low_user = f"guest_{datetime.now():%H%M%S}"
    print(f">> Low: 3 failed logins for {low_user}")
    for i in range(3):
        now = datetime.now()
        line = (
            f"{_auth_ts(now)} server sshd[{pid_base + i}]: "
            f"Failed password for {low_user} from 10.0.0.51 port 22 ssh2"
        )
        append(AUTH_LOG, line)
        time.sleep(0.1)

    # Medium (score 6): 8 rapid failed SSH logins for 'hacker'
    print("\n>> Medium: 8 failed logins for hacker")
    for i in range(8):
        now = datetime.now()
        line = (
            f"{_auth_ts(now)} server sshd[{pid_base + 10 + i}]: "
            f"Failed password for hacker from 192.168.1.200 port 22 ssh2"
        )
        append(AUTH_LOG, line)
        time.sleep(0.5)

    # High (score 15): 3 unauthorized access attempts to /admin
    print("\n>> High: 3 x GET /admin -> 403")
    for i in range(3):
        now = datetime.now()
        line = (
            f"10.0.0.99 - - [{_web_ts(now)}] "
            f'"GET /admin HTTP/1.1" 403 512 "-" "Mozilla/5.0"'
        )
        append(WEB_LOG, line)
        time.sleep(0.5)

    # Critical (score 20): 20 rapid failed logins for 'admin'
    print("\n>> Critical: 20 rapid failed logins for admin")
    for i in range(20):
        now = datetime.now()
        line = (
            f"{_auth_ts(now)} server sshd[{pid_base + 30 + i}]: "
            f"Failed password for admin from 10.0.0.50 port 22 ssh2"
        )
        append(AUTH_LOG, line)

    print("\nSimulation complete.")
    print(f"  auth log : 31 lines appended  ({AUTH_LOG})")
    print(f"  web log  :  3 lines appended  ({WEB_LOG})")
    print("\nRun `python main.py` to process the logs and see all four severity tiers.")


if __name__ == "__main__":
    main()
