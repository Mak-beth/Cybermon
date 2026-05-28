# UPGRADE.md
# Live monitoring upgrade — implementation plan for Claude Code.
# This extends the existing system. Nothing already built gets deleted or rewritten.
# Read this fully before starting any phase.

---

## What this upgrade does

The current system is a batch pipeline: run it once, it reads log files, writes to the database,
launches the dashboard showing a frozen snapshot. Done.

This upgrade turns it into a live monitoring system:
- A watcher runs continuously, tailing log files for new lines
- Each new line is parsed, detected, scored, and stored immediately
- The browser dashboard updates automatically without any refresh
- The trend chart shows violations by type per hour for today — not a 7-day total

---

## What does NOT change

Every file in src/ingestion/, src/detection/, src/scoring/, src/storage/ stays untouched.
All 100 existing tests must continue passing after every phase.
config/config.yaml structure is unchanged.
The batch pipeline (main.py) continues to work as before.

---

## Stack additions (no new libraries outside existing requirements.txt)

- Log tailing: Python standard library only — `open()` + `time.sleep()` in a thread
- Live push: Flask's built-in streaming response — `Response(stream_with_context(...))`
- Browser listener: native browser `EventSource` API — no JS libraries needed
- Trend query: new SQL query in storage/reader.py — no schema changes

---

## New files after upgrade complete

```
src/ingestion/watcher.py              ← tails log files continuously
src/dashboard/templates/live.html     ← live feed page showing violations as they arrive
tests/test_watcher.py                 ← unit tests for watcher
tests/test_live.py                    ← integration tests for SSE route and live page
```

## Modified files after upgrade complete

```
src/storage/reader.py                 ← add get_trend_by_hour_today()
src/dashboard/app.py                  ← add /stream and /live routes, update /trend
src/dashboard/templates/trend.html    ← replace with 3-line hourly chart
src/dashboard/static/js/charts.js    ← add initHourlyTrendChart()
main.py                               ← add --live flag to start watcher mode
requirements.txt                      ← no changes needed
RUNNING.md                            ← update with new commands
```

---

## Phase U1 — Log file watcher

**Goal:** Build a watcher that tails one or more log files and processes new lines as they arrive.

### File to create: `src/ingestion/watcher.py`

Must contain:

`tail_file(filepath: str, callback, poll_interval: float = 0.5)`
- Opens the file, seeks to the end (so it only reads NEW lines, not historical ones)
- Loops: reads any new lines since last read, calls `callback(line, log_type)` for each
- Sleeps `poll_interval` seconds between reads
- Runs forever until the calling thread is stopped
- Does not crash if the file is temporarily unreadable — catches exceptions, logs a warning, continues

`LogWatcher`  class:
- `__init__(self, config: dict)` — stores config
- `start(self, auth_log: str, web_log: str, on_violation)` — starts two daemon threads,
  one tailing auth_log with log_type="auth", one tailing web_log with log_type="web"
- `on_violation` is a callback: `on_violation(scored_violation: dict)` — called every time
  a new violation is detected and scored from a new log line
- Internally: for each new line, calls the ingestion parser → preprocessor → detection → scoring
  pipeline on that single event. If a violation is detected, calls on_violation with the
  fully scored violation dict (all 10 keys including likelihood, impact, risk_score, severity).
- `stop()` — sets a stop flag so threads exit cleanly on next poll cycle

**Important:** The watcher processes one line at a time. It does NOT batch lines before detecting.
For failed_logins detection, it must maintain a per-username rolling buffer of recent FAILED events
in memory (a dict keyed by username, storing a deque of recent timestamps). Each new FAILED line
checks whether the buffer for that username now exceeds the threshold within the time window.
This replaces the pandas-based batch detection for real-time use only — the batch detector is untouched.

### File to create: `tests/test_watcher.py`

Tests must cover:
- `tail_file` calls callback for each new line written to a file after the watcher starts
- `tail_file` does NOT call callback for lines that existed before the watcher started
- `LogWatcher` calls `on_violation` when a brute force pattern is written to a watched file
- `LogWatcher` does not crash if the watched file does not exist yet — waits and retries

### Verification

```bash
pytest tests/test_watcher.py -v
pytest tests/ -v  # all 100+ tests must still pass
```

### Acceptance criteria

- [ ] `tail_file` reads only new lines written after it starts — never historical lines
- [ ] `LogWatcher.start()` spawns two daemon threads (one per log file)
- [ ] `on_violation` is called within 2 seconds of a matching line being written to the file
- [ ] Watcher survives a temporarily missing or unreadable file without crashing
- [ ] All tests in `tests/test_watcher.py` pass
- [ ] All 100 existing tests still pass

### Dependencies
Phases 0–6 complete. No changes to any existing file in this phase.

---

## Phase U2 — Live storage writer and SSE route

**Goal:** Add a `/stream` route to Flask that pushes new violations to the browser as Server-Sent Events,
and a `/live` page that displays them in real time.

### Modify: `src/dashboard/app.py`

Add these imports at the top:
```python
import json
import queue
import threading
from flask import Response, stream_with_context
```

Add a module-level violation queue:
```python
_violation_queue = queue.Queue()
```

Add a `post_violation(v: dict)` function that puts a scored violation onto `_violation_queue`.
This is what the LogWatcher callback will call.

Add route `GET /stream`:
- Returns a `Response` with `mimetype="text/event-stream"` and `Cache-Control: no-cache`
- Uses `stream_with_context` with a generator that:
  - Loops: calls `_violation_queue.get(timeout=30)`
  - On each violation, yields `f"data: {json.dumps(v)}\n\n"` (SSE format)
  - On timeout (no new violations for 30s), yields `": keepalive\n\n"` (SSE comment, keeps connection alive)
  - Catches `GeneratorExit` cleanly

Add route `GET /live`:
- Renders `live.html`
- Passes `db_path` so the template can show existing violations on load

### Create: `src/dashboard/templates/live.html`

Extends `base.html`. Must show:

- A heading "Live monitor" with a pulsing green dot indicator showing the watcher is connected
- A table identical in columns to `violations.html` (timestamp, type, username, source IP, resource, score, severity badge)
- New violations prepend to the top of the table as they arrive — most recent first
- A JavaScript `EventSource` that connects to `/stream` and on each `message` event:
  - Parses the JSON
  - Creates a new table row with the correct severity badge colour
  - Prepends it to the table body with a brief highlight animation (fades from amber to transparent)
  - Updates a "last updated" timestamp shown above the table
- If the SSE connection drops, shows a "Reconnecting..." status — `EventSource` reconnects automatically
- On page load, fetches existing violations from the database via a call to `get_all_violations_with_scores`
  and populates the table (so the page is not empty when first opened)

### Modify: `src/dashboard/templates/base.html`

Add "Live" nav link pointing to `/live` alongside the existing nav items.

### Create: `tests/test_live.py`

Tests must cover:
- `GET /live` returns HTTP 200
- `GET /stream` returns HTTP 200 with `Content-Type: text/event-stream`
- Posting a violation to `_violation_queue` causes it to appear in the SSE stream

### Verification

```bash
pytest tests/test_live.py -v
pytest tests/ -v
```

Manual verification:
```
1. Run: venv\Scripts\python.exe main.py --live
2. Open http://127.0.0.1:5000/live
3. Append a brute-force pattern to logs/samples/auth.log manually
4. Confirm a new row appears in the live table within 2 seconds without refreshing
```

### Acceptance criteria

- [ ] `GET /stream` returns `Content-Type: text/event-stream`
- [ ] Keepalive comment sent every 30 seconds of inactivity
- [ ] New violation appears on `/live` page within 2 seconds of being written to the log file
- [ ] Existing violations are shown on page load (not an empty table)
- [ ] Severity badges on live page use the same colours as violations.html
- [ ] All tests in `tests/test_live.py` pass
- [ ] All existing tests still pass

### Dependencies
Phase U1 complete. `LogWatcher` must be working before the SSE route is built.

---

## Phase U3 — Trend chart fix

**Goal:** Replace the current 7-day total trend chart with a per-hour, per-violation-type chart for today.

### Modify: `src/storage/reader.py`

Add new function `get_trend_by_hour_today(db_path: str) -> dict`:

Returns a dict with this exact structure:
```python
{
  "hours": ["00", "01", "02", ..., "23"],   # all 24 hours always present
  "failed_logins":       [0, 0, 2, 0, ...], # count per hour
  "unauthorized_access": [0, 0, 0, 5, ...],
  "off_hours_login":     [0, 1, 0, 0, ...]
}
```

SQL approach:
- Query violations WHERE DATE(timestamp) = DATE('now')
- Group by strftime('%H', timestamp) and violation_type
- Fill missing hours with 0 (not every hour will have violations)
- Return all 24 hours always — the chart x-axis is fixed at 00–23

Keep the old `get_trend_data()` function — do not remove it. It is used by existing tests.

### Modify: `src/dashboard/app.py`

Update the `/trend` route to call `get_trend_by_hour_today(DB_PATH)` instead of `get_trend_data()`.
Pass the returned dict directly to the template.

### Modify: `src/dashboard/templates/trend.html`

Replace the current bar chart with a multi-line chart using Chart.js.
Pass `trend_data` from the route to the template.
Call `initHourlyTrendChart(hours, failed, unauthorized, offhours)` from charts.js.
Show a clear heading: "Today's violations by hour".
If all counts are zero, show the empty state message.

### Modify: `src/dashboard/static/js/charts.js`

Add `initHourlyTrendChart(hours, failed, unauthorized, offhours)`:
- Chart type: `"line"`
- X-axis: the 24-hour labels array
- Three datasets, one per violation type:
  - Failed logins: colour `#dc3545` (red)
  - Unauthorized access: colour `#ffc107` (amber)
  - Off-hours login: colour `#3fb950` (green)
- `tension: 0.3` for smooth curves
- `fill: false`
- Points shown only where count > 0 (`pointRadius` via per-point array or threshold)
- Y-axis starts at 0, integer ticks only

Keep `initSeverityChart` and `initTrendChart` — do not remove them.

### Modify: `src/storage/reader.py` — also update `get_trend_data` default

Change `get_trend_data(db_path, days=7)` default to `days=365` so the old trend route
always returns data regardless of when the demo runs. This fixes the stale-chart gap.

### Tests

Add tests to `tests/test_storage.py`:
- `get_trend_by_hour_today` returns a dict with keys `hours`, `failed_logins`, `unauthorized_access`, `off_hours_login`
- `hours` always contains exactly 24 entries
- Each count list has exactly 24 entries
- All counts are integers >= 0

### Verification

```bash
pytest tests/test_storage.py -v
pytest tests/ -v
```

Manual: open `http://127.0.0.1:5000/trend` — should show three lines on a 24-hour x-axis.

### Acceptance criteria

- [ ] `get_trend_by_hour_today` returns all 24 hours always, even if no violations that hour
- [ ] Three separate lines on the chart — one per violation type
- [ ] X-axis shows hours 00–23
- [ ] Y-axis is integer-only, starts at zero
- [ ] Old `get_trend_data` still exists and existing tests still pass
- [ ] `get_trend_data` default window changed to 365 days

### Dependencies
Phase U2 complete. `app.py` must already have the new routes before modifying the trend route.

---

## Phase U4 — Single launch command and startup script

**Goal:** One command starts everything. No manual steps after cloning and installing.

### Modify: `main.py`

Add a `--live` flag to the argument parser:
```python
parser.add_argument("--live", action="store_true",
                    help="Start live monitoring mode — watches log files continuously")
```

When `--live` is passed:
1. Load config
2. Call `init_db`
3. Run the batch pipeline once on existing logs (same as current behaviour) — seeds the database
4. Print summary
5. Start `LogWatcher` with `on_violation` set to `post_violation` from app.py
6. Print: `Live monitoring active — watching logs/samples/auth.log and logs/samples/access.log`
7. Print: `Dashboard → http://127.0.0.1:5000`
8. Print: `Press Ctrl+C to stop.`
9. Launch Flask dashboard
10. LogWatcher threads are daemons — they stop automatically when Flask stops

When `--live` is NOT passed: existing behaviour unchanged (batch run + dashboard).

### Create: `start.bat` (Windows batch file in project root)

```bat
@echo off
cd /d "%~dp0"
if not exist venv\Scripts\activate.bat (
    echo Creating virtual environment...
    py -m venv venv
)
call venv\Scripts\activate.bat
echo Installing dependencies...
pip install -r requirements.txt -q
echo Starting Cybermon in live mode...
venv\Scripts\python.exe main.py --live
```

This single file:
- Creates the venv if it does not exist
- Activates it
- Installs/updates dependencies silently
- Starts the full live system

A developer cloning the repo for the first time runs `start.bat` once and everything is ready.

### Update: `RUNNING.md`

Add a new section at the top:

```
## Quickstart (one command)

Double-click start.bat — or run it from the terminal:

    start.bat

This creates the venv if needed, installs dependencies, and launches Cybermon
in live monitoring mode. Open http://127.0.0.1:5000 in your browser.
```

Update the manual steps section to reflect `--live` flag.
Add a table showing the difference between batch mode and live mode.

### Acceptance criteria

- [ ] `start.bat` runs end-to-end on a machine with only Python installed — no other manual steps
- [ ] `start.bat` is safe to run multiple times — does not error if venv already exists
- [ ] `python main.py --live` starts watcher threads AND launches dashboard in one command
- [ ] `python main.py` (no flag) still works exactly as before
- [ ] Dashboard is accessible at `http://127.0.0.1:5000` within 10 seconds of running start.bat
- [ ] RUNNING.md updated with quickstart section

### Dependencies
Phases U1, U2, U3 all complete.

---

## Summary table

| Phase | Deliverable | Touches | Complexity |
|-------|-------------|---------|------------|
| U1 | Log file watcher — tails files, calls pipeline per new line | New: watcher.py, test_watcher.py | Medium |
| U2 | SSE route + live page — pushes violations to browser in real time | Modified: app.py, base.html. New: live.html, test_live.py | Medium-High |
| U3 | Trend chart fix — per-hour, per-type, today only | Modified: reader.py, app.py, trend.html, charts.js | Medium |
| U4 | Single launch command — start.bat + --live flag | Modified: main.py, RUNNING.md. New: start.bat | Low |

## Constraint reminder

- No new libraries. Everything uses Python standard library + the four already in requirements.txt.
- All 100 existing tests must pass after every phase.
- Detection, scoring, and storage logic is not modified in any phase.
- The batch pipeline (`python main.py` with no flags) must work identically after the upgrade.
