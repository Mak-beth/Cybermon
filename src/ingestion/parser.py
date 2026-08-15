import re
from datetime import datetime
from typing import Optional

_AUTH_LINE = re.compile(
    r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+'
    r'(\S+)\s+'
    r'(\S+\[\d+\]):\s+'
    r'(.+)$'
)
# Windows OpenSSH file log: "<pid> <YYYY-MM-DD HH:MM:SS.mmm> <message>"
# No hostname and no process[pid]: token — just a leading PID and an ISO timestamp.
_WINDOWS_AUTH_LINE = re.compile(
    r'^\d+\s+'
    r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+'
    r'(.+)$'
)
_FAILED_MSG       = re.compile(r'Failed password for (?:invalid user )?(\S+) from (\S+) port')
_ACCEPTED_MSG     = re.compile(r'Accepted password for (\S+) from (\S+) port')
# "Invalid user X from IP" — appears without "Failed password" prefix in some sshd versions
_INVALID_USER_MSG = re.compile(r'Invalid user (\S+) from (\S+)')

_ACCESS_LINE = re.compile(
    r'^(\S+)\s+\S+\s+\S+\s+'
    r'\[([^\]]+)\]\s+'
    r'"(\S+)\s+(\S+)\s+\S+"\s+'
    r'(\d{3})\s+'
    r'\S+'
)

# Apache error log: [Day Mon DD HH:MM:SS YYYY] [level] [client IP] message
_APACHE_ERROR_LINE = re.compile(
    r'^\[(\w{3} \w{3}\s+\d{1,2} \d{2}:\d{2}:\d{2} \d{4})\]\s+'
    r'\[(\w+)\]\s+'
    r'(?:\[client\s+(\S+?)\]\s+)?'
    r'(.+)$'
)
_APACHE_ERROR_PATH = re.compile(r'(/\S+?)/*$')


def parse_auth_log_line(line: str) -> Optional[dict]:
    if not line or not line.strip():
        return None
    m = _AUTH_LINE.match(line)
    if m:
        # Linux syslog: "Aug 16 03:17:28 host sshd[6376]: <message>"
        timestamp_str, hostname, process, message = m.groups()
    else:
        # Windows OpenSSH: "<pid> <YYYY-MM-DD HH:MM:SS.mmm> <message>"
        wm = _WINDOWS_AUTH_LINE.match(line)
        if not wm:
            return None
        timestamp_str, message = wm.groups()
        hostname, process = "localhost", "sshd"

    failed = _FAILED_MSG.search(message)
    if failed:
        return {
            "timestamp": timestamp_str,
            "hostname": hostname,
            "process": process,
            "username": failed.group(1),
            "source_ip": failed.group(2),
            "status": "failure",
            "raw": line,
        }
    accepted = _ACCEPTED_MSG.search(message)
    if accepted:
        return {
            "timestamp": timestamp_str,
            "hostname": hostname,
            "process": process,
            "username": accepted.group(1),
            "source_ip": accepted.group(2),
            "status": "success",
            "raw": line,
        }
    # "Invalid user X from IP" — same meaning as a failed login, no port suffix
    inv_user = _INVALID_USER_MSG.search(message)
    if inv_user:
        return {
            "timestamp": timestamp_str,
            "hostname": hostname,
            "process": process,
            "username": inv_user.group(1),
            "source_ip": inv_user.group(2),
            "status": "failure",
            "raw": line,
        }
    return None


def parse_access_log_line(line: str) -> Optional[dict]:
    if not line or not line.strip():
        return None
    # Combined Log Format (standard Apache access log)
    m = _ACCESS_LINE.match(line)
    if m:
        source_ip, timestamp_str, method, resource, status_code = m.groups()
        return {
            "timestamp": timestamp_str,
            "source_ip": source_ip,
            "method": method,
            "resource": resource,
            "status_code": status_code,
            "raw": line,
        }
    # Apache error log format: [Day Mon DD HH:MM:SS YYYY] [level] [client IP] message
    # Only lines with a client IP carry enough info for detection.
    err_m = _APACHE_ERROR_LINE.match(line)
    if err_m:
        ts_raw, level, client_ip, message = err_m.groups()
        if not client_ip:
            return None  # daemon-level message — no request data
        try:
            ts_norm = re.sub(r'\s+', ' ', ts_raw.strip())
            dt = datetime.strptime(ts_norm, "%a %b %d %H:%M:%S %Y")
            ts_reformatted = dt.strftime("%d/%b/%Y:%H:%M:%S")
        except ValueError:
            return None
        msg_lower = message.lower()
        if "forbidden" in msg_lower or "denied" in msg_lower:
            status_code = "403"
        elif level == "error":
            status_code = "500"
        else:
            return None  # notice/info — not an error event
        path_m = _APACHE_ERROR_PATH.search(message)
        resource = path_m.group(1) if path_m else "/"
        return {
            "timestamp": ts_reformatted,
            "source_ip": client_ip,
            "method": "GET",
            "resource": resource,
            "status_code": status_code,
            "raw": line,
        }
    return None
