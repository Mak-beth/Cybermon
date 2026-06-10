"""Live-socket probe of the ingest endpoint — R11-A behaviour over real HTTP.

Starts the Flask app on 127.0.0.1:5099 in a daemon thread and fires real
requests at it.  Run manually:
    venv/Scripts/python scripts/endpoint_probe.py
"""
import os
import sys
import threading
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import requests
import yaml

import server.ingest_endpoint as ie

PORT = 5099
URL = f"http://127.0.0.1:{PORT}/ingest"
KEY = yaml.safe_load(open("config/config.yaml", encoding="utf-8"))["server"]["api_key"]

t = threading.Thread(
    target=lambda: ie.ingest_app.run(host="127.0.0.1", port=PORT,
                                     debug=False, use_reloader=False),
    daemon=True,
)
t.start()
time.sleep(1.5)

results = []

def check(name: str, expected: int, actual: int) -> None:
    status = "PASS" if expected == actual else "FAIL"
    results.append((status, name, expected, actual))
    print(f"[{status}] {name}: expected {expected}, got {actual}")

# 1. No key
r = requests.post(URL, json={"host": "probe", "lines": []}, timeout=5)
check("missing key -> 401", 401, r.status_code)

# 2. Wrong key
r = requests.post(URL, json={"host": "probe", "lines": []},
                  headers={"X-API-Key": "nope"}, timeout=5)
check("wrong key -> 401", 401, r.status_code)

# 3. Correct key, empty batch
r = requests.post(URL, json={"host": "probe", "lines": []},
                  headers={"X-API-Key": KEY}, timeout=5)
check("correct key -> 200", 200, r.status_code)

# 4. Bad host identifier
r = requests.post(URL, json={"host": "x; rm -rf /", "lines": []},
                  headers={"X-API-Key": KEY}, timeout=5)
check("shell-meta host -> 400", 400, r.status_code)

# 5. Oversized batch
r = requests.post(URL, json={"host": "probe", "lines": ["x"] * 5001},
                  headers={"X-API-Key": KEY}, timeout=5)
check("5001 lines -> 413", 413, r.status_code)

# 6. Real brute force across two batches (stateful detection over the wire)
stamp = datetime.now().strftime("%b %d %H:%M:%S")
line = f"{stamp} server sshd[1]: Failed password for probeuser from 7.7.7.7 port 22 ssh2"
requests.post(URL, json={"host": "probe", "lines": [line]},
              headers={"X-API-Key": KEY}, timeout=5)
r = requests.post(URL, json={"host": "probe", "lines": [line]},
                  headers={"X-API-Key": KEY}, timeout=5)
detected = r.json().get("violations_detected", 0)
check("slow brute force 2nd batch detects >= 1", True, detected >= 1)

failed = [r for r in results if r[0] == "FAIL"]
print(f"\n{len(results) - len(failed)}/{len(results)} probes passed")
sys.exit(1 if failed else 0)
