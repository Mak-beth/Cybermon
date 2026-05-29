# Cybermon

> A rule-based cybersecurity monitoring tool that ingests Linux auth and Apache web logs, detects threats in real time, scores risk, and surfaces findings on a live web dashboard.

---

## What it does

Cybermon watches your log files continuously. When a suspicious pattern appears — a brute-force SSH attempt, someone probing restricted URLs, or a successful login at 3 AM — it detects it, scores it, persists it to a database, and pushes it to the browser instantly over a Server-Sent Events stream. No page refresh needed.

```
Log files  ──►  Detection engine  ──►  Risk scorer  ──►  SQLite DB
                                                              │
                                                         Flask dashboard
                                                              │
                                                     Browser (live SSE)
```

---

## Detection rules

| Rule | Trigger | Example |
|------|---------|---------|
| **Failed logins** | N failed SSH attempts within a time window | 8 failures in 10 min for `admin` |
| **Unauthorized access** | HTTP 401 / 403 on restricted resources | `GET /admin 403` |
| **Off-hours login** | Successful SSH login outside business hours | Login at 02:14 on a weekday |

---

## Risk scoring

Every violation gets a **Likelihood × Impact** score mapped to a severity band:

```
Score  1–4   →  Low       (green)
Score  5–9   →  Medium    (amber)
Score 10–16  →  High      (red)
Score 17–25  →  Critical  (dark red)
```

All thresholds live in `config/config.yaml` — nothing is hardcoded.

---

## Dashboard pages

| URL | What you see |
|-----|-------------|
| `/` | Live stat cards, severity doughnut chart, counts by type — updates without refresh |
| `/violations` | Full ranked violation table, sorted by risk score |
| `/violations/<id>` | Detail view with score breakdown |
| `/trend` | Today's violations by hour, split by type (line chart) |
| `/live` | Real-time stream — new rows appear as logs are written |
| `/export` | Download a CSV of all violations |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        main.py                          │
│  argparse ──► run_pipeline() ──► app.run()              │
│                                      │                  │
│              ┌───────────────────────┤                  │
│              │  --live flag          │                  │
│              │  LogWatcher threads   │                  │
│              └──────────┬────────────┘                  │
└─────────────────────────┼───────────────────────────────┘
                          │
          ┌───────────────▼──────────────┐
          │        src/ingestion/        │
          │  reader → parser → normalize │
          └───────────────┬──────────────┘
                          │
          ┌───────────────▼──────────────┐
          │        src/detection/        │
          │  failed_logins               │
          │  unauthorized_access         │
          │  off_hours                   │
          └───────────────┬──────────────┘
                          │
          ┌───────────────▼──────────────┐
          │        src/scoring/          │
          │  likelihood × impact         │
          │  severity bands from config  │
          └───────────────┬──────────────┘
                          │
          ┌───────────────▼──────────────┐
          │        src/storage/          │
          │  SQLite — events,            │
          │  violations, risk_scores     │
          └───────────────┬──────────────┘
                          │
          ┌───────────────▼──────────────┐
          │       src/dashboard/         │
          │  Flask routes                │
          │  SSE /stream endpoint        │
          │  /api/summary JSON endpoint  │
          └──────────────────────────────┘
```

---

## Quick start (Windows)

Double-click **`start.bat`** or run from a terminal:

```bat
.\start.bat
```

Then open **http://127.0.0.1:5000** in your browser.

To simulate live attack traffic in a second terminal:

```bat
venv\Scripts\python.exe simulate.py
```

Violations appear on `/live` and the overview counters update in real time.

---

## Manual setup

```bash
py -m venv venv
venv\Scripts\activate

pip install -r requirements.txt

# Batch mode (processes sample logs once, then serves dashboard)
venv\Scripts\python.exe main.py

# Live mode (batch pipeline + watches logs/live/ for new lines)
venv\Scripts\python.exe main.py --live

# Point at your own logs
venv\Scripts\python.exe main.py --live --auth-log path/to/auth.log --web-log path/to/access.log

# Run tests
venv\Scripts\pytest.exe tests/ -v
```

---

## Project layout

```
Cybermon/
├── config/config.yaml          # All thresholds and settings
├── data/                       # SQLite database (auto-created)
├── exports/                    # CSV report downloads
├── logs/
│   ├── samples/                # Fixed test fixtures (never modified)
│   └── live/                   # Live demo target (simulate.py writes here)
├── src/
│   ├── ingestion/              # reader, parser, preprocessor, watcher
│   ├── detection/              # rules: failed_logins, unauth, off_hours
│   ├── scoring/                # likelihood, impact, severity bands
│   ├── storage/                # db init, writer, reader
│   └── dashboard/              # Flask app, templates, static assets
├── tests/                      # 121 tests across 6 test files
├── main.py                     # Pipeline + live mode entry point
├── simulate.py                 # Appends synthetic attack lines to logs/live/
├── start.bat                   # One-click Windows launcher
└── PROGRESS.md                 # Living build log
```

---

## Stack

| Library | Role |
|---------|------|
| Python 3.10+ | Core language |
| Flask 3.x | Web dashboard and SSE |
| pandas | Time-window sliding analysis |
| SQLite (stdlib) | Local persistence |
| PyYAML | Config loading |
| pytest | 121 unit + integration tests |

---

## Test coverage

```
tests/test_ingestion.py     18 tests   log parsing and normalisation
tests/test_detection.py     17 tests   all three detection rules
tests/test_scoring.py       31 tests   likelihood, impact, severity bands
tests/test_storage.py       26 tests   DB init, read, write, trend queries
tests/test_integration.py   13 tests   end-to-end pipeline + dashboard routes
tests/test_live.py           8 tests   SSE stream and live monitor page
tests/test_watcher.py        8 tests   log tailing and real-time detection
─────────────────────────────────────
Total                       121 tests  all passing
```
