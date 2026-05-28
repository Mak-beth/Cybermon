# PROGRESS.md
# Living log — updated after every phase and every significant decision.
# Never rewrite history. Append only.

---

## How to Use This File

After completing a phase:
1. Copy the phase block template below
2. Fill in every field honestly — failures included
3. Commit this file alongside the phase code

After making a decision that affects the plan:
1. Add a Decision Log entry with the date and reasoning
2. Note if the decision invalidates any acceptance criterion in PHASES.md

---

## Phase Block Template

```
### Phase N — [Phase Name]
**Status:** Complete | In Progress | Blocked | Failed
**Date Started:**
**Date Completed:**

**Acceptance Criteria Results:**
- [ ] Criterion 1
- [ ] Criterion 2

**What was built:**

**What didn't work and how it was fixed:**

**Deviations from PHASES.md (if any):**

**Commit hash:**
```

---

## Decision Log Template

```
### Decision — [Short Title]
**Date:**
**Context:**
**Options considered:**
**Decision made:**
**Reason:**
**Impact on PHASES.md:**
```

---

## Log

### Phase 0 — Scaffold
**Status:** Complete
**Date Started:** 2026-05-27
**Date Completed:** 2026-05-27

**Acceptance Criteria Results:**
- [x] `python -m venv venv` runs without error
- [x] `venv\Scripts\activate` activates the environment
- [x] `pip install -r requirements.txt` installs all packages without error
- [x] `python main.py` runs and prints config values without error
- [x] All folders and files exist
- [x] `config/config.yaml` loads via `yaml.safe_load()` without error

**What was built:**
Full project scaffold: all directories (config, data, exports, logs/samples, src with five subpackages, tests), all __init__.py package markers, .gitkeep files for empty dirs, config/config.yaml with all detection/scoring/storage/dashboard settings, main.py stub that loads and prints config, requirements.txt (flask, pandas, pyyaml, pytest), README.md, PHASES.md copied from spec. venv created with py -m venv; all four packages installed successfully.

**What didn't work and how it was fixed:**
`python` alias not available on this machine — py launcher (py.exe) used instead. venv\Scripts\python.exe used for all subsequent runs.

**Deviations from PHASES.md (if any):**
None.

**Commit hash:**

---

### Phase 1 — Log Ingestion and Preprocessing
**Status:** Complete
**Date Started:** 2026-05-28
**Date Completed:** 2026-05-28

**Acceptance Criteria Results:**
- [x] `preprocess_log_file('logs/samples/auth.log', 'auth')` returns at least 15 dicts (returned 25)
- [x] `preprocess_log_file('logs/samples/access.log', 'web')` returns at least 15 dicts (returned 22)
- [x] Every returned dict contains all six standard schema keys
- [x] `timestamp` field is a Python `datetime` object, not a string
- [x] `parse_auth_log_line` returns `None` for a blank or malformed line without raising an exception
- [x] All 18 tests in `tests/test_ingestion.py` pass

**What was built:**
`src/ingestion/reader.py` — reads non-empty lines, raises FileNotFoundError on missing file.
`src/ingestion/parser.py` — regex parsers for Linux auth log and Apache Combined Log Format; handles `invalid user` variant; returns None on no-match.
`src/ingestion/preprocessor.py` — normalize_event maps parsed dicts to 6-key schema; auth timestamps get current year prepended (no year in auth log format); access timestamps parsed with strptime including year.
`logs/samples/auth.log` — 25 lines: 8 admin failures in 5-min window, 3 testuser failures across 30 min, 5 successful logins (1 at 02:14 for off-hours detection).
`logs/samples/access.log` — 22 lines: 5x 403 /admin, 3x 401 /config, 10x 200 normal, 2x 403 other restricted.

**What didn't work and how it was fixed:**
Nothing significant. Auth timestamp year is derived from `datetime.now().year` since the auth log format omits it.

**Deviations from PHASES.md (if any):**
`action` field uses `"ssh_login"` (not `"ssh_failed"`) with `status_code="FAILED"/"SUCCESS"` to keep the field clean and consistent with the detection rules that filter on `status_code`.

**Commit hash:**

---

### Phase 2 — Violation Detection Engine
**Status:** Complete
**Date Started:** 2026-05-28
**Date Completed:** 2026-05-28

**Acceptance Criteria Results:**
- [x] `run_detection` returns at least 3 violations from the synthetic logs (returned 12)
- [x] At least one violation of type `failed_logins` detected from `auth.log`
- [x] At least one violation of type `unauthorized_access` detected from `access.log`
- [x] At least one violation of type `off_hours_login` detected from `auth.log`
- [x] Every violation dict contains all six schema keys
- [x] Changing `threshold` changes the number of `failed_logins` violations detected
- [x] All 17 tests in `tests/test_detection.py` pass

**What was built:**
`src/detection/rules/failed_logins.py` — groups FAILED events by username with pandas, slides a pd.Timedelta window, flags username when count exceeds threshold; one violation per username.
`src/detection/rules/unauthorized_access.py` — matches status_code against trigger_codes (as strings) and resource against restricted_resources; one violation per matching event.
`src/detection/rules/off_hours.py` — flags SUCCESS events whose timestamp falls outside business_days/business_hours from config; one violation per event.
`src/detection/detector.py` — calls all three rules and returns combined list without mutating input.

**What didn't work and how it was fixed:**
Nothing significant.

**Deviations from PHASES.md (if any):**
None.

**Commit hash:**

---

### Phase 2 Fix — Two-Pointer Sliding Window
**Date:** 2026-05-28
**File:** `src/detection/rules/failed_logins.py`
**Change:** Replaced nested loop with two-pointer approach as required by updated PHASES.md. Left pointer advances whenever the window exceeds the configured duration; violation emitted when window size exceeds threshold. All 17 detection tests confirmed passing after fix.

---

### Phase 3 — Risk Scoring
**Status:** Complete
**Date Started:** 2026-05-28
**Date Completed:** 2026-05-28

**Acceptance Criteria Results:**
- [x] Every scored violation contains `likelihood`, `impact`, `risk_score`, and `severity`
- [x] `risk_score` equals `likelihood * impact` for every violation
- [x] Score 4 → Low, 5 → Medium, 10 → High, 17 → Critical
- [x] Tier boundary tests pass: 4→Low, 5→Medium, 9→Medium, 10→High, 16→High, 17→Critical, 25→Critical
- [x] `assign_severity` reads tier ranges from config — no hardcoded numbers in scorer.py
- [x] All 31 tests in `tests/test_scoring.py` pass

**What was built:**
`src/scoring/rules.py` — `get_likelihood` extracts failure count from detail string via regex; `get_impact` maps username/resource to impact value. All lookup logic isolated here.
`src/scoring/scorer.py` — five functions; `assign_severity` reads config tiers with no hardcoded numbers; `score_violation` uses dict unpacking to avoid mutating input.

**Scores from synthetic logs:**
- failed_logins (admin, 8 in 10 min): L=3 × I=4 = 12 → High
- unauthorized_access (/admin, /.env): L=3 × I=5 = 15 → High
- unauthorized_access (/config, /wp-admin): L=3 × I=3 = 9 → Medium
- off_hours_login (alice 02:14): L=2 × I=3 = 6 → Medium

**What didn't work and how it was fixed:**
Nothing significant.

**Deviations from PHASES.md (if any):**
None.

**Commit hash:**

---

### Phase 4 — Storage Layer
**Status:** Complete
**Date Started:** 2026-05-28
**Date Completed:** 2026-05-28

**Acceptance Criteria Results:**
- [x] `init_db` creates all three tables without error
- [x] Calling `init_db` twice does not raise an error or duplicate tables
- [x] `insert_events` batch inserts all events without error
- [x] `insert_violation` returns the correct integer row id
- [x] `get_all_violations_with_scores` returns results ordered by `risk_score` descending
- [x] `get_summary_counts` returns correct totals matching what was inserted
- [x] `get_trend_data` returns a list of dicts each with `date` and `count` keys
- [x] `get_violation_detail` returns a single dict for a valid id
- [x] All 21 tests in `tests/test_storage.py` pass
- [x] Test uses `data/test_phase4.db` and deletes it after — confirmed by final test

**What was built:**
`src/storage/db.py` — `init_db` creates data dir and all three tables with `CREATE TABLE IF NOT EXISTS`; idempotent by design.
`src/storage/writer.py` — `insert_events` batch inserts via `executemany`; derives `log_type` from `action` field; `insert_violation` returns `lastrowid`; `insert_risk_score` links to violation by id.
`src/storage/reader.py` — `get_all_violations_with_scores` JOINs violations + risk_scores ordered DESC; `get_summary_counts` returns pre-initialized dicts for all types/severities; `get_violation_detail` returns empty dict on missing id; `get_trend_data` uses SQLite DATE() grouping.

**Summary from synthetic logs:**
12 violations stored: 1 failed_logins, 10 unauthorized_access, 1 off_hours_login. By severity: 5 Medium, 7 High.

**What didn't work and how it was fixed:**
Nothing significant.

**Deviations from PHASES.md (if any):**
None.

**Commit hash:**

---

### Phase 5 — Flask Dashboard
**Status:** Complete
**Date Started:** 2026-05-28
**Date Completed:** 2026-05-28

**Acceptance Criteria Results:**
- [x] `/` loads without error and shows summary counts and doughnut chart
- [x] `/violations` table sorted by risk_score descending, severity badges correct colours
- [x] `/violations/<id>` shows plain-language score sentence on one line
- [x] `/violations/99999` returns 404 for unknown id
- [x] `/trend` renders bar chart with data points
- [x] `/export` downloads CSV with correct headers and all 12 rows
- [x] Dashboard runs on 127.0.0.1:5000 with no extra setup
- [x] No SQL in app.py — all data through reader.py
- [x] No hardcoded values in templates

**What was built:**
`src/dashboard/app.py` — 5 routes + 404 handler; reads db_path and host/port from config; calls init_db on startup so db is created if missing; sys.path patched so it runs from any working directory.
`templates/base.html` — sticky nav, Chart.js CDN, CSS link.
`templates/index.html` — stat cards for total + per-severity, doughnut chart, by-type and by-severity tables.
`templates/violations.html` — clickable table rows linking to detail view, colour-coded severity badges.
`templates/detail.html` — all violation fields, score breakdown sentence, visual L × I = score display.
`templates/trend.html` — bar chart; empty state message if no data.
`static/css/style.css` — dark GitHub-style theme, severity badge colours match Table 3.3 exactly.
`static/js/charts.js` — initSeverityChart (doughnut) and initTrendChart (bar).

**What didn't work and how it was fixed:**
Score sentence was split across two lines in the template — moved to a single line so it renders and matches cleanly.

**Deviations from PHASES.md (if any):**
None.

**Commit hash:**

---

### Phase 6 — Full Pipeline & Integration Tests
**Status:** Complete
**Date Started:** 2026-05-28
**Date Completed:** 2026-05-28

**Acceptance Criteria Results:**
- [x] `python main.py` runs the full pipeline end-to-end and launches the Flask dashboard
- [x] `--auth-log` and `--web-log` CLI flags accepted; defaults point to synthetic logs
- [x] Pipeline prints progress lines (1/5 … 5/5) and summary
- [x] Running `main.py` twice produces the same violation count (idempotent)
- [x] All 13 tests in `tests/test_integration.py` pass
- [x] Full test suite (100 tests across all 5 test files) passes with 0 failures

**What was built:**
`main.py` (full rewrite) — `run_pipeline(auth_log, web_log, config)` wires all five phases into one call: init DB, clear tables, ingest, store events, detect, score, store violations + scores, print summary. `main()` adds argparse (`--auth-log`, `--web-log`) then launches Flask after the pipeline completes.
`_clear_tables` resets `sqlite_sequence` rows alongside DELETE so AUTOINCREMENT IDs restart at 1 on every run.
`tests/test_integration.py` — 13 integration tests: event count (47), violation count (12), all three violation types present, DB count matches detection output, all scored have valid severity, risk_score == likelihood × impact, idempotency, dashboard routes / /violations /violations/1 → 200, /violations/99999 → 404, CSV headers correct, CSV row count matches DB.

**What didn't work and how it was fixed:**
`test_dashboard_detail_returns_200` failed because `INTEGER PRIMARY KEY AUTOINCREMENT` kept incrementing IDs across DELETE-and-reinsert cycles, so `/violations/1` returned 404 after the first test run. Fixed by adding `DELETE FROM sqlite_sequence WHERE name IN ('risk_scores', 'violations', 'events')` to `_clear_tables`, which resets the counters so IDs restart at 1 on every pipeline run.

**Deviations from PHASES.md (if any):**
None.

**Commit hash:**

---

### Phase U1 — Log File Watcher
**Status:** Complete
**Date Started:** 2026-05-28
**Date Completed:** 2026-05-28

**Acceptance Criteria Results:**
- [x] `tail_file` reads only new lines written after it starts — never historical lines
- [x] `LogWatcher.start()` spawns two daemon threads (one per log file)
- [x] `on_violation` is called within 2 seconds of a matching line being written to the file
- [x] Watcher survives a temporarily missing or unreadable file without crashing
- [x] All 8 tests in `tests/test_watcher.py` pass
- [x] All 100 existing tests still pass (108 total)

**What was built:**
`src/ingestion/watcher.py`:
- `tail_file(filepath, log_type, callback, poll_interval=0.5, stop_event=None)` — opens file, seeks to end to skip existing content, loops calling `callback(line, log_type)` for every new line; catches FileNotFoundError and other exceptions, logs a warning, and retries — never crashes.
- `LogWatcher` class — `__init__` stores config and creates a `threading.Event` stop flag and per-username `deque` buffer for rolling failed-login detection. `start()` spawns two daemon threads via `tail_file`, one per log file. `stop()` sets the stop flag. Per-line processing: auth FAILED lines update the rolling buffer and emit a `failed_logins` violation when count exceeds the threshold; auth SUCCESS lines are checked against off-hours rules; web lines are checked for unauthorized access. All violations are scored before `on_violation` is called.
`tests/test_watcher.py` — 8 tests covering: new lines delivered, existing lines skipped, correct log_type passed to callback, thread survival on missing file, two daemon threads spawned, brute force triggers violation with all 10 scored keys, no crash on missing file, violation delivered within 2 seconds.

**What didn't work and how it was fixed:**
Nothing significant. Per-line processing reuses the existing `detect_unauthorized_access` and `detect_off_hours_logins` functions directly (they already operate on single-item lists). Only `failed_logins` needed a custom rolling buffer since the batch detector is pandas-based.

**Deviations from UPGRADE.md (if any):**
`tail_file` signature extended with `log_type` (second positional arg) and optional `stop_event` (fifth arg) beyond the spec's listed signature. Both are required: `log_type` so the callback receives it as specified; `stop_event` so `LogWatcher.stop()` can signal threads cleanly.

**Commit hash:**

---

### Phase U2 — SSE Route and Live Monitor Page
**Status:** Complete
**Date Started:** 2026-05-28
**Date Completed:** 2026-05-28

**Acceptance Criteria Results:**
- [x] `GET /stream` returns `Content-Type: text/event-stream`
- [x] New violation pushed to `_violation_queue` appears in SSE stream as `data: {...}\n\n`
- [x] Keepalive comment (`": keepalive\n\n"`) sent after 30s of inactivity
- [x] `GET /live` returns HTTP 200; existing violations shown on page load
- [x] Severity badges on live page use same colours as violations.html
- [x] All 8 tests in `tests/test_live.py` pass
- [x] All 108 existing tests still pass (116 total)

**What was built:**
`src/dashboard/app.py` — added `_violation_queue` (module-level queue), `_SSE_STOP` sentinel, `post_violation(v)`, `_sse_generator(q)` (private generator; yields SSE data lines, stops on sentinel or keepalive-comments on timeout), `/stream` route (streaming Response, Cache-Control: no-cache), `/live` route (renders live.html with existing violations from DB).
`src/dashboard/templates/live.html` — extends base.html; shows existing violations on load; `EventSource` connects to `/stream`; each message prepends a new row with amber-fade highlight animation; status dot pulses green when connected, turns red on disconnect; "Reconnecting..." shown on `onerror`.
`src/dashboard/templates/base.html` — "Live" nav link added (green, matching Export CSV style).
`src/dashboard/static/css/style.css` — added `.live-link`, `.dot` variants with `dot-pulse` keyframe animation, `.live-new` with `row-highlight` keyframe fade.
`tests/test_live.py` — 8 tests: /live returns 200, existing violations in page body, /stream returns 200, /stream content-type, /stream delivers SSE data for queued violation, `post_violation` enqueues item, `_sse_generator` yields correct SSE format, datetime fields serialized to string.
`UPGRADE.md` — added to repo root (read-only reference).

**What didn't work and how it was fixed:**
Initial stream tests each took 30 seconds. Root cause: Flask/Werkzeug test client drains the response generator when the `with client:` block exits, hitting the 30s `queue.Empty` timeout. Fixed by adding `_SSE_STOP = object()` sentinel — tests put it in the queue after their test violation, making the generator finite. Production behavior is unchanged (real clients never put `_SSE_STOP` in the queue).

**Deviations from UPGRADE.md (if any):**
None.

**Commit hash:**

---

### Phase U3 — Hourly Trend Chart
**Status:** Complete
**Date Started:** 2026-05-28
**Date Completed:** 2026-05-28

**Acceptance Criteria Results:**
- [x] `get_trend_by_hour_today` returns all 24 hours always, even with no violations that hour
- [x] Three separate lines on chart — one per violation type (red / amber / green)
- [x] X-axis shows hours 00–23
- [x] Y-axis is integer-only, starts at zero
- [x] Old `get_trend_data` still exists and existing tests still pass
- [x] `get_trend_data` default window changed to 365 days
- [x] All 5 new tests in `tests/test_storage.py` pass
- [x] All 116 existing tests still pass (121 total)

**What was built:**
`src/storage/reader.py` — added `get_trend_by_hour_today(db_path)`: queries violations WHERE DATE(timestamp) = DATE('now'), groups by strftime('%H', ...) and violation_type, fills all 24 hour buckets with 0 before applying query results; returns `{"hours": ["00".."23"], "failed_logins": [...], "unauthorized_access": [...], "off_hours_login": [...]}`. Changed `get_trend_data` default from `days=7` to `days=365`.
`src/dashboard/app.py` — `/trend` route now calls `get_trend_by_hour_today` and passes `trend_data` dict to template; `get_trend_by_hour_today` added to imports.
`src/dashboard/templates/trend.html` — replaced 7-day bar chart with 3-line hourly chart; heading "Today's violations by hour"; empty state when all counts are zero; passes 4 arrays to `initHourlyTrendChart`.
`src/dashboard/static/js/charts.js` — added `initHourlyTrendChart(hours, failed, unauthorized, offhours)`: Chart.js line chart, 3 datasets (failed logins #dc3545, unauthorized #ffc107, off-hours #3fb950), tension 0.3, fill false, point radius 4 only where count > 0, Y-axis integer-only from zero. `initSeverityChart` and `initTrendChart` kept.
`tests/test_storage.py` — 5 new tests: correct keys returned, 24 hours in list, 24 entries per count list, all counts non-negative integers, today's violation appears at correct hour index.

**What didn't work and how it was fixed:**
Nothing significant.

**Deviations from UPGRADE.md (if any):**
None.

**Commit hash:**

---
