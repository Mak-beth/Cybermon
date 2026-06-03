"""
Appends realistic log lines to the sample log files, producing violations
across all four severity tiers when the pipeline is run afterwards.

Run this script, then run `python main.py` to see all four tiers in the GUI.

Tier   | Pattern                          | L | I | Score
-------|----------------------------------|---|---|------
Low      3 failed logins for guest        2   2    4
Medium   8 failed logins for hacker       3   2    6
High     3 x GET /admin -> 403            3   5   15
Critical 20 failed logins for admin       5   4   20
"""
import time
from datetime import datetime

# Write to the same files that main.py reads by default.
AUTH_LOG = "logs/samples/auth.log"
WEB_LOG  = "logs/samples/access.log"


def _auth_ts(now: datetime) -> str:
    return now.strftime("%b %d %H:%M:%S").replace(" 0", "  ")


def _web_ts(now: datetime) -> str:
    return now.strftime("%d/%b/%Y:%H:%M:%S +0000")


def append(filepath: str, line: str) -> None:
    with open(filepath, "a") as f:
        f.write(line + "\n")
    print(f"[+] {filepath}: {line}")


def main():
    print("Cybermon simulator starting.\n")

    pid_base = 2000

    # ------------------------------------------------------------------
    # Low (score 4): 3 failed logins for 'guest'
    #   count=3 > threshold(2) -> detection trigger
    #   likelihood: count<=5 -> 2
    #   impact:     'guest' not in HIGH_IMPACT_USERS -> 2
    #   score:      2 x 2 = 4 -> Low
    # ------------------------------------------------------------------
    print(">> Low: 3 failed logins for guest")
    for i in range(3):
        now = datetime.now()
        line = (
            f"{_auth_ts(now)} server sshd[{pid_base + i}]: "
            f"Failed password for guest from 10.0.0.51 port 22 ssh2"
        )
        append(AUTH_LOG, line)
        time.sleep(0.1)

    # ------------------------------------------------------------------
    # Medium (score 6): 8 rapid failed SSH logins for 'hacker'
    #   count=8 > threshold(2) -> detection trigger
    #   likelihood: count<=9 -> 3
    #   impact:     'hacker' not in HIGH_IMPACT_USERS -> 2
    #   score:      3 x 2 = 6 -> Medium
    # ------------------------------------------------------------------
    print("\n>> Medium: 8 failed logins for hacker")
    for i in range(8):
        now = datetime.now()
        line = (
            f"{_auth_ts(now)} server sshd[{pid_base + 10 + i}]: "
            f"Failed password for hacker from 192.168.1.200 port 22 ssh2"
        )
        append(AUTH_LOG, line)
        time.sleep(0.5)

    # ------------------------------------------------------------------
    # High (score 15): 3 unauthorized access attempts to /admin
    #   likelihood: unauthorized_access -> 3
    #   impact:     /admin in HIGH_IMPACT_RESOURCES -> 5
    #   score:      3 x 5 = 15 -> High
    # ------------------------------------------------------------------
    print("\n>> High: 3 x GET /admin -> 403")
    for i in range(3):
        now = datetime.now()
        line = (
            f"10.0.0.99 - - [{_web_ts(now)}] "
            f'"GET /admin HTTP/1.1" 403 512 "-" "Mozilla/5.0"'
        )
        append(WEB_LOG, line)
        time.sleep(0.5)

    # ------------------------------------------------------------------
    # Critical (score 20): 20 rapid failed logins for 'admin'
    #   All appended without sleep so all fall inside the 10-minute window.
    #   count=20 > threshold(2) -> detection trigger
    #   likelihood: count>19 -> 5
    #   impact:     'admin' in HIGH_IMPACT_USERS -> 4
    #   score:      5 x 4 = 20 -> Critical
    # ------------------------------------------------------------------
    print("\n>> Critical: 20 rapid failed logins for admin")
    for i in range(20):
        now = datetime.now()
        line = (
            f"{_auth_ts(now)} server sshd[{pid_base + 30 + i}]: "
            f"Failed password for admin from 10.0.0.50 port 22 ssh2"
        )
        append(AUTH_LOG, line)
        # No sleep: keep all 20 inside the 10-minute detection window

    print("\nSimulation complete.")
    print(f"  auth.log  : 31 lines appended  ({AUTH_LOG})")
    print(f"  access.log:  3 lines appended  ({WEB_LOG})")
    print("\nRun `python main.py` to process the logs and see all four severity tiers.")


if __name__ == "__main__":
    main()
