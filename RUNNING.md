# Running Cybermon

Step-by-step instructions for getting the project running locally.
Updated after each phase. Current state: **Upgrades U1–U4 complete**.

---

## Quickstart (Windows — live mode)

Double-click `start.bat` or run it from a terminal:

```bat
start.bat
```

This single script:
1. Creates a virtual environment if one does not exist
2. Installs all dependencies from `requirements.txt`
3. Runs the batch pipeline against the sample logs
4. Starts live monitoring (watches log files for new activity)
5. Launches the Flask dashboard at `http://127.0.0.1:5000`

---

## Batch mode vs live mode

| Mode | Command | What it does |
|------|---------|--------------|
| Batch (default) | `venv\Scripts\python.exe main.py` | Processes sample logs once, then serves the dashboard |
| Live | `venv\Scripts\python.exe main.py --live` | Batch pipeline first, then watches log files for new lines in real time; new violations appear instantly on `/live` |
| Custom logs | `... main.py --auth-log path/to/auth.log --web-log path/to/access.log` | Points both modes at your own log files |

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

Installs: `flask`, `pandas`, `pyyaml`, `pytest`.

---

## 4. Verify config loads (Phase 0 check)

```bash
venv\Scripts\python.exe main.py
```

Expected output:

```
=== Cybermon Config ===
Failed login threshold : 5
Time window (min)      : 10
...
Config loaded successfully.
```

---

## 5. Run the test suite (Phases 1–6)

```bash
venv\Scripts\pytest.exe tests/ -v
```

Expected: **100 tests, all passing** across `test_ingestion.py`, `test_detection.py`, `test_scoring.py`, `test_storage.py`, `test_integration.py`.

---

## 6. Run the full pipeline and launch the dashboard

```bash
venv\Scripts\python.exe main.py
```

This single command:
1. Ingests the synthetic logs
2. Detects violations
3. Scores them
4. Writes everything to `data/cybermon.db`
5. Prints a summary
6. Launches the Flask dashboard on `http://127.0.0.1:5000`

Expected output:
```
[ 1/5 ] Ingesting logs...
        47 events parsed
[ 2/5 ] Running detection...
        12 violations detected
[ 3/5 ] Scoring violations...
[ 4/5 ] Storing results...
[ 5/5 ] Done.

=== Cybermon Summary ===
  Events parsed    : 47
  Violations found : 12
  By type          : {'failed_logins': 1, 'unauthorized_access': 10, 'off_hours_login': 1}
  By severity      : {'Low': 0, 'Medium': 5, 'High': 7, 'Critical': 0}

Launching dashboard → http://127.0.0.1:5000
Press Ctrl+C to stop.
```

You can also point it at custom log files:
```bash
venv\Scripts\python.exe main.py --auth-log path/to/auth.log --web-log path/to/access.log
```

Press `Ctrl+C` to stop the server.

---

## 7. Dashboard pages

Then open your browser at:

| URL | Page |
|-----|------|
| `http://127.0.0.1:5000/` | Overview — total count, severity chart |
| `http://127.0.0.1:5000/violations` | Ranked violation list |
| `http://127.0.0.1:5000/violations/1` | Single violation detail |
| `http://127.0.0.1:5000/trend` | Today's violations by hour (line chart, 3 types) |
| `http://127.0.0.1:5000/live` | Live monitor — real-time stream of new violations |
| `http://127.0.0.1:5000/export` | Download CSV report |

---

## Configuration

All thresholds and settings live in `config/config.yaml`. No values are hardcoded in source files.

| Setting | Default | Effect |
|---------|---------|--------|
| `detection.failed_logins.threshold` | 5 | Minimum failures in window to trigger alert |
| `detection.failed_logins.time_window_minutes` | 10 | Rolling window size |
| `detection.unauthorized_access.trigger_codes` | [403, 401] | HTTP status codes that count as unauthorised |
| `dashboard.port` | 5000 | Port the Flask server listens on |

---

## Phase completion status

| Phase | What it adds | How to run |
|-------|-------------|------------|
| 0 | Scaffold, config | `venv\Scripts\python.exe main.py` |
| 1 | Log ingestion | `venv\Scripts\pytest.exe tests/test_ingestion.py -v` |
| 2 | Violation detection | `venv\Scripts\pytest.exe tests/test_detection.py -v` |
| 3 | Risk scoring | `venv\Scripts\pytest.exe tests/test_scoring.py -v` |
| 4 | SQLite storage | `venv\Scripts\pytest.exe tests/test_storage.py -v` |
| 5 | Flask dashboard | `venv\Scripts\python.exe src/dashboard/app.py` |
| 6 | Full pipeline + integration tests | `venv\Scripts\python.exe main.py` / `venv\Scripts\pytest.exe tests/ -v` |
| U1 | Log file watcher (real-time tailing) | `venv\Scripts\pytest.exe tests/test_watcher.py -v` |
| U2 | SSE route + live monitor page | `venv\Scripts\pytest.exe tests/test_live.py -v` |
| U3 | Hourly trend chart | `venv\Scripts\pytest.exe tests/test_storage.py -v` |
| U4 | `--live` flag + `start.bat` | `start.bat` or `main.py --live` |
