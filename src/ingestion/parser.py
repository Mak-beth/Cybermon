import re
from typing import Optional

_AUTH_LINE = re.compile(
    r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+'
    r'(\S+)\s+'
    r'(\S+\[\d+\]):\s+'
    r'(.+)$'
)
_FAILED_MSG  = re.compile(r'Failed password for (?:invalid user )?(\S+) from (\S+) port')
_ACCEPTED_MSG = re.compile(r'Accepted password for (\S+) from (\S+) port')

_ACCESS_LINE = re.compile(
    r'^(\S+)\s+\S+\s+\S+\s+'
    r'\[([^\]]+)\]\s+'
    r'"(\S+)\s+(\S+)\s+\S+"\s+'
    r'(\d{3})\s+'
    r'\S+'
)


def parse_auth_log_line(line: str) -> Optional[dict]:
    if not line or not line.strip():
        return None
    m = _AUTH_LINE.match(line)
    if not m:
        return None
    timestamp_str, hostname, process, message = m.groups()
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
    return None


def parse_access_log_line(line: str) -> Optional[dict]:
    if not line or not line.strip():
        return None
    m = _ACCESS_LINE.match(line)
    if not m:
        return None
    source_ip, timestamp_str, method, resource, status_code = m.groups()
    return {
        "timestamp": timestamp_str,
        "source_ip": source_ip,
        "method": method,
        "resource": resource,
        "status_code": status_code,
        "raw": line,
    }
