"""
Appends realistic log lines to the sample log files one at a time,
simulating live activity for use with `python main.py --live`.
"""
import time
from datetime import datetime

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
    print("Cybermon simulator starting — Ctrl+C to stop.\n")

    pid_base = 2000

    # --- 8 rapid failed SSH logins for hacker from 192.168.1.200 ---
    print(">> Brute-force sequence (hacker / 192.168.1.200)")
    for i in range(8):
        now = datetime.now()
        line = (
            f"{_auth_ts(now)} server sshd[{pid_base + i}]: "
            f"Failed password for hacker from 192.168.1.200 port 22 ssh2"
        )
        append(AUTH_LOG, line)
        time.sleep(1)

    # --- 3 unauthorized access attempts to /admin from 10.0.0.99 ---
    print("\n>> Unauthorized access sequence (10.0.0.99 -> /admin)")
    for i in range(3):
        now = datetime.now()
        line = (
            f"10.0.0.99 - - [{_web_ts(now)}] "
            f'"GET /admin HTTP/1.1" 403 512 "-" "Mozilla/5.0"'
        )
        append(WEB_LOG, line)
        time.sleep(1)

    # --- 1 successful SSH login for root (triggers off-hours if outside 09:00-17:00) ---
    print("\n>> Successful root login")
    now = datetime.now()
    line = (
        f"{_auth_ts(now)} server sshd[{pid_base + 10}]: "
        f"Accepted password for root from 192.168.1.200 port 22 ssh2"
    )
    append(AUTH_LOG, line)

    print("\nSimulation complete. 12 lines appended.")
    print(f"  auth.log : 9 lines  ({AUTH_LOG})")
    print(f"  access.log: 3 lines ({WEB_LOG})")


if __name__ == "__main__":
    main()
