"""R11-E1 four-tier verification — run after simulate.py.

Processes the configured log files into a TEMPORARY database and prints
severity counts.  data/cybermon.db is never touched.
"""
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import yaml
from main import run_pipeline

cfg = yaml.safe_load(open("config/config.yaml", encoding="utf-8"))
tmp_db = os.path.join(tempfile.mkdtemp(), "tiercheck.db")
cfg["storage"]["db_path"] = tmp_db

auth_log = cfg.get("auth_log_path", "logs/auth.log")
web_log = cfg.get("web_log_path", "logs/access.log")
run_pipeline(auth_log, web_log, cfg)

conn = sqlite3.connect(tmp_db)
print("\n--- severity counts ---")
rows = list(conn.execute(
    "SELECT severity, COUNT(*) FROM risk_scores GROUP BY severity"
))
for sev, n in rows:
    print(f"{sev:10s} | {n}")
conn.close()
os.remove(tmp_db)

present = {sev for sev, _ in rows}
missing = {"Low", "Medium", "High", "Critical"} - present
if missing:
    print(f"\nFAIL: missing tiers: {sorted(missing)}")
    sys.exit(1)
print("\nPASS: all four severity tiers present")
