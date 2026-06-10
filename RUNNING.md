# Running CyberMon

Step-by-step instructions for getting the project running locally.
Current state: **Rework phases R0–R7 complete** — native PyQt6 desktop application.

---

## Quickstart (Windows)

Double-click `start.bat`, or run it from a terminal:

```bat
start.bat
```

This single script:
1. Creates a Python virtual environment if one does not exist
2. Installs all dependencies from `requirements.txt`
3. Runs the detection pipeline against the sample log files
4. Opens the CyberMon desktop window

No browser is required. The application is a native Windows desktop window.

---

## Prerequisites

- Python 3.10 or later
- Git

Verify with:

```
py --version
git --version
```

---

## 1. Clone the repository

```bash
git clone https://github.com/Mak-beth/Cybermon.git
cd Cybermon
```

---

## 2. Create and activate the virtual environment

```bash
py -m venv venv
venv\Scripts\activate
```

Your prompt should now show `(venv)`.

---

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

Installs: `PyQt6`, `PyQtGraph`, `flask`, `pandas`, `pyyaml`, `requests`, `pytest`.

---

## 4. Run the test suite

```bash
venv\Scripts\pytest.exe tests/ -v
```

Expected: **142 tests, all passing**.

---

## 5. Launch the application

```bash
venv\Scripts\python.exe main.py
```

Or double-click `start.bat`.

**First run:** A three-screen setup wizard appears before the main window.

| Wizard screen | What to do |
|---------------|-----------|
| Mode selection | Choose "Just this computer" (standalone) or "Monitor multiple computers" (network) |
| Configuration | Set log file paths, business hours, and brute-force threshold |
| Confirmation | Review settings and click Finish |

After the wizard completes, the main window opens automatically. On all subsequent launches the wizard is skipped.

---

## 6. Application panels

The sidebar on the left switches between five panels:

| Panel | What it shows |
|-------|--------------|
| Overview | Total violation count, severity breakdown cards, doughnut chart, per-type progress bars |
| Violations | Sortable table of all violations, colour-coded severity badges, host filter, Export CSV |
| Live Feed | Real-time stream of new violations as they are detected (polls every 3 seconds) |
| Trend | Line charts — violations by hour today and by day over the last 7 days |
| Settings | Edit log paths, business hours, brute-force threshold; re-run setup wizard |

---

## 7. Generate demo data (all four severity tiers)

Run the simulator to append realistic log lines to the sample files, then relaunch the app:

```bash
venv\Scripts\python.exe simulate.py
venv\Scripts\python.exe main.py
```

The simulator produces violations across all four tiers:

| Tier | Pattern | Score |
|------|---------|-------|
| Low | 3 failed logins for `guest` | 4 |
| Medium | 8 failed logins for `hacker` | 6 |
| High | 3 × GET /admin returning 403 | 15 |
| Critical | 20 failed logins for `admin` | 20 |

---

## 8. Export violations to CSV

In the Violations panel, set the host filter if needed, then click **Export CSV**. A save dialog opens. The file contains one row per visible violation with columns: `timestamp`, `violation_type`, `source_host`, `likelihood`, `impact`, `risk_score`, `severity`, `recommended_action`, `log_excerpt`.

---

## 9. Network mode (multi-machine monitoring)

1. Run the setup wizard on the server machine and choose "Monitor multiple computers".
2. On each machine you want to monitor, run `CyberMonAgent.exe` (or `agent_main.py` from source) and point it at the server IP.
3. The server receives log lines via HTTP POST on port 5001 and processes them through the detection pipeline automatically.

---

## 10. Network Mode Security

The ingest endpoint authenticates agents with a shared API key. Every POST from an agent must carry an `X-API-Key` header that matches the server's configured key; requests without it are rejected with HTTP 401.

**Changing the key (do this before any real deployment):**

1. On the server machine, edit `server.api_key` in `config/config.yaml`.
2. On each agent machine, edit `api_key` in `agent_config.yaml`.
3. The two values must match exactly. Restart both sides after changing.

The default value `CHANGE_ME_BEFORE_DEPLOY` is intentionally obvious — replace it with a long random string.

**Known limitations:**

- Traffic is plaintext HTTP. On untrusted networks, run the agent and server over a VPN or a dedicated management VLAN. TLS support is future work.
- The host identifier sent by agents is validated (max 64 chars, alphanumeric/dot/hyphen/underscore) but trusted — a compromised agent machine can still misreport its `host_id`.
- Request bodies are capped at 2MB and 5000 lines per batch to prevent flooding.

---

## 11. Configuration

All thresholds and settings live in `config/config.yaml`. Changes take effect on the next pipeline run.

| Setting | Default | Effect |
|---------|---------|--------|
| `mode` | `standalone` | `standalone` or `network` |
| `detection.failed_logins.threshold` | 2 | Minimum failures in window to trigger alert |
| `detection.failed_logins.time_window_minutes` | 10 | Rolling window size |
| `detection.off_hours_logins.business_hours_start` | `08:00` | Start of business day |
| `detection.off_hours_logins.business_hours_end` | `18:00` | End of business day |
| `storage.db_path` | `data/cybermon.db` | SQLite database location |

Settings can also be changed from the Settings panel inside the app without editing the file directly.

---

## 12. Running from source (developer mode)

Point the pipeline at custom log files:

```bash
venv\Scripts\python.exe main.py --auth-log path/to/auth.log --web-log path/to/access.log
```

Run only the tests for a specific module:

```bash
venv\Scripts\pytest.exe tests/test_detection.py -v
venv\Scripts\pytest.exe tests/test_scoring.py -v
venv\Scripts\pytest.exe tests/test_storage.py -v
```
