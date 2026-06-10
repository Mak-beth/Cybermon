"""CyberMon pipeline performance benchmark — R11-E3.

Measures the full pipeline (parse -> normalise -> detect -> score -> store)
against the real LogHub datasets in logs/real/.  Uses a temporary database
in tmp/ which is deleted afterwards; data/cybermon.db is never touched.

Run from the project root:
    venv/Scripts/python scripts/benchmark.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import yaml

from src.ingestion.parser import parse_auth_log_line, parse_access_log_line
from src.ingestion.preprocessor import normalize_event
from src.detection.detector import run_detection
from src.scoring.scorer import score_all_violations
from src.storage.db import init_db
from src.storage.writer import (
    insert_events,
    insert_violation,
    insert_risk_score,
    find_triggering_event_id,
)

SSH_LOG = os.path.join(ROOT, "logs", "real", "SSH_2k.log")
APACHE_LOG = os.path.join(ROOT, "logs", "real", "Apache_2k.log")
TMP_DIR = os.path.join(ROOT, "tmp")
TMP_DB = os.path.join(TMP_DIR, "benchmark.db")


def main() -> int:
    for path in (SSH_LOG, APACHE_LOG):
        if not os.path.exists(path):
            print(f"ERROR: missing real log file: {path}")
            return 1

    with open(os.path.join(ROOT, "config", "config.yaml"), encoding="utf-8") as fh:
        config = yaml.safe_load(fh)

    ssh_lines = open(SSH_LOG, encoding="utf-8", errors="replace").read().splitlines()
    apache_lines = open(APACHE_LOG, encoding="utf-8", errors="replace").read().splitlines()
    total_lines = len(ssh_lines) + len(apache_lines)

    # --- Pipeline: parse -> normalise -> detect -> score ---
    t0 = time.perf_counter()

    events = []
    parsed_count = 0
    for line in ssh_lines:
        parsed = parse_auth_log_line(line)
        if parsed is not None:
            parsed_count += 1
            events.append(normalize_event(parsed, "auth"))
    for line in apache_lines:
        parsed = parse_access_log_line(line)
        if parsed is not None:
            parsed_count += 1
            events.append(normalize_event(parsed, "web"))

    violations = run_detection(events, config)
    scored = score_all_violations(violations, config)

    pipeline_time = time.perf_counter() - t0

    # --- Database write ---
    os.makedirs(TMP_DIR, exist_ok=True)
    if os.path.exists(TMP_DB):
        os.remove(TMP_DB)

    t1 = time.perf_counter()
    init_db(TMP_DB)
    insert_events(events, TMP_DB)
    for v in scored:
        v["triggering_event_id"] = find_triggering_event_id(v, TMP_DB)
        vid = insert_violation(v, TMP_DB)
        insert_risk_score(vid, v, TMP_DB)
    db_time = time.perf_counter() - t1

    db_size_kb = os.path.getsize(TMP_DB) / 1024

    by_type = {"failed_logins": 0, "unauthorized_access": 0, "off_hours_login": 0}
    for v in scored:
        if v["violation_type"] in by_type:
            by_type[v["violation_type"]] += 1

    rate = len(events) / pipeline_time if pipeline_time > 0 else 0

    print("=== CyberMon Performance Benchmark ===")
    print(f"Log files processed     : SSH_2k.log ({len(ssh_lines)} lines), "
          f"Apache_2k.log ({len(apache_lines)} lines)")
    print(f"Total lines attempted   : {total_lines}")
    print(f"Lines parsed            : {parsed_count} "
          f"({parsed_count / total_lines * 100:.1f}%)")
    print(f"Events normalised       : {len(events)}")
    print(f"Pipeline execution time : {pipeline_time:.3f} seconds")
    print(f"Processing rate         : {rate:.0f} events/second")
    print(f"Violations detected     : {len(scored)} (breakdown by type below)")
    print(f"  failed_logins         : {by_type['failed_logins']}")
    print(f"  unauthorized_access   : {by_type['unauthorized_access']}")
    print(f"  off_hours_login       : {by_type['off_hours_login']}")
    print(f"Database write time     : {db_time:.3f} seconds")
    print(f"Total time (incl. DB)   : {pipeline_time + db_time:.3f} seconds")
    print(f"DB size after run       : {db_size_kb:.1f} KB")

    # --- Cleanup ---
    os.remove(TMP_DB)
    try:
        os.rmdir(TMP_DIR)
    except OSError:
        pass   # directory not empty — leave it

    return 0


if __name__ == "__main__":
    sys.exit(main())
