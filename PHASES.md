# PHASES.md
# Static reference — created once, never edited after project start.
# All implementation decisions, acceptance criteria, and file trees live here.

---

## Sequencing Rationale

Backend-first, dashboard-last. Each layer depends on the one before it:
- You cannot detect violations without parsed log data (Phase 1 before Phase 2)
- You cannot score without detected violations (Phase 2 before Phase 3)
- You cannot store without scored violations (Phase 3 before Phase 4)
- You cannot display without stored data (Phase 4 before Phase 5)
- You cannot integrate without all five components working in isolation (Phase 5 last)

Phase 0 is scaffold only — no logic, just structure and repo files.
Phase 6 is UAT and final report writeup — no code changes after Phase 5.

---

## Status Snapshot (as of Phase 2 completion)

| Phase | Status |
|-------|--------|
| 0 | Complete |
| 1 | Complete |
| 2 | Complete — one known issue (see Phase 2 note) |
| 3 | Not started |
| 4 | Not started |
| 5 | Not started |
| 6 | Not started |

---

## Phase 0 — Scaffold

**Status: COMPLETE**

**Goal:** Set up the project structure, config system, repo files, and virtual environment.

### Files Created

| File | Purpose |
|------|---------|
| `README.md` | Project overview, stack, how to run |
| `PHASES.md` | This file |
| `PROGRESS.md` | Living log, updated after every phase |
| `requirements.txt` | flask, pandas, pyyaml, pytest |
| `config/config.yaml` | All thresholds and settings |
| `main.py` | Entry point stub |
| `src/__init__.py` | Package marker |
| `src/ingestion/__init__.py` | Package marker |
| `src/detection/__init__.py` | Package marker |
| `src/scoring/__init__.py` | Package marker |
| `src/storage/__init__.py` | Package marker |
| `src/dashboard/__init__.py` | Package marker |
| `tests/__init__.py` | Package marker |

### config/config.yaml — Locked Structure

```yaml
detection:
  failed_logins:
    threshold: 5
    time_window_minutes: 10
  unauthorized_access:
    restricted_resources: ["/admin", "/wp-admin", "/phpmyadmin", "/config", "/.env"]
    trigger_codes: [403, 401]
  off_hours_logins:
    business_days: [0, 1, 2, 3, 4]
    business_hours_start: "08:00"
    business_hours_end: "18:00"
scoring:
  severity_tiers:
    low:      { min: 1,  max: 4  }
    medium:   { min: 5,  max: 9  }
    high:     { min: 10, max: 16 }
    critical: { min: 17, max: 25 }
storage:
  db_path: "data/cybermon.db"
dashboard:
  host: "127.0.0.1"
  port: 5000
  debug: false
  export_path: "exports/"
```

### Acceptance Criteria — All Passed

- [x] `python -m venv venv` runs without error
- [x] `venv\Scripts\activate` activates the environment
- [x] `pip install -r requirements.txt` installs all four packages without error
- [x] `python main.py` runs and prints config values without error
- [x] All folders and files exist
- [x] `config/config.yaml` loads via `yaml.safe_load()` without error

### Known Deviation
`py` launcher used instead of `python` on this machine. Use `py` or `venv\Scripts\python.exe` for all commands.

---

## Phase 1 — Log Ingestion and Preprocessing

**Status: COMPLETE**

**Goal:** Build the ingestion module that reads raw log files and outputs normalized event records.

### Files Created

| File | Purpose |
|------|---------|
| `src/ingestion/reader.py` | Reads raw log files from disk, returns lines |
| `src/ingestion/parser.py` | Parses lines into structured dicts using regex |
| `src/ingestion/preprocessor.py` | Normalizes parsed dicts into consistent schema |
| `logs/samples/auth.log` | Synthetic Linux auth log (25 lines) |
| `logs/samples/access.log` | Synthetic web access log (22 lines) |
| `tests/test_ingestion.py` | 18 unit tests — all passing |

### Standard Event Schema (locked — all downstream phases depend on this)

Every normalized event dict must contain exactly these six keys:

```python
{
  "timestamp": datetime,      # Python datetime object, not a string
  "username":  str | None,
  "source_ip": str | None,
  "resource":  str | None,
  "action":    str,            # "ssh_login" for auth, "http_request" for web
  "status_code": str           # "FAILED" / "SUCCESS" for auth, "200"/"403" etc for web
}
```

### Known Limitation
Auth log timestamps have no year field. The preprocessor injects `datetime.now().year`.
This is acceptable for a prototype. Logged in PROGRESS.md as a known limitation.

### Acceptance Criteria — All Passed

- [x] `preprocess_log_file('logs/samples/auth.log', 'auth')` returns at least 15 dicts (returned 25)
- [x] `preprocess_log_file('logs/samples/access.log', 'web')` returns at least 15 dicts (returned 22)
- [x] Every returned dict contains all six standard schema keys
- [x] `timestamp` field is a Python `datetime` object, not a string
- [x] `parse_auth_log_line` returns `None` for a blank or malformed line without raising an exception
- [x] All 18 tests in `tests/test_ingestion.py` pass

---

## Phase 2 — Violation Detection Engine

**Status: COMPLETE — fix required before Phase 3 starts**

**Goal:** Build three rule-based detectors that identify policy violations from normalized event records.

### Files Created

| File | Purpose |
|------|---------|
| `src/detection/detector.py` | Calls all three rules, returns combined violation list |
| `src/detection/rules/failed_logins.py` | Rule 1: repeated failed logins with rolling time window |
| `src/detection/rules/unauthorized_access.py` | Rule 2: HTTP 403/401 on restricted resources |
| `src/detection/rules/off_hours.py` | Rule 3: successful logins outside business hours |
| `tests/test_detection.py` | 17 unit tests — all passing |

### Standard Violation Schema (locked — all downstream phases depend on this)

Every violation dict must contain exactly these six keys:

```python
{
  "violation_type": str,    # "failed_logins" | "unauthorized_access" | "off_hours_login"
  "timestamp":     datetime,
  "username":      str | None,
  "source_ip":     str | None,
  "resource":      str | None,
  "detail":        str       # human-readable description
}
```

### Fix Required Before Phase 3

The current `detect_failed_logins` uses a nested loop that is fragile for edge cases
where failures cluster near a window boundary. It works on the current synthetic logs
but can produce incorrect counts on real-world log patterns.

**CC must apply this fix before starting Phase 3:**

Rewrite `detect_failed_logins` in `src/detection/rules/failed_logins.py` to use a
two-pointer sliding window:

```
For each username group (sorted by timestamp):
  Use two pointers left=0, right=0
  Advance right one step at a time
  When timestamps[right] - timestamps[left] > window, advance left
  When (right - left + 1) > threshold, emit one violation and stop for this username
  The violation timestamp = timestamps[left] (start of the triggering window)
  The violation detail = f"{right - left + 1} failed logins in {window_minutes} min for user '{username}'"
```

After rewriting, run `pytest tests/test_detection.py -v` and confirm all 17 tests still pass.
Then commit with message: "fix: two-pointer sliding window in failed_logins detector"

### Acceptance Criteria — All Passed

- [x] `run_detection` returns at least 3 violations from the synthetic logs (returned 12)
- [x] At least one violation of type `failed_logins` detected from `auth.log`
- [x] At least one violation of type `unauthorized_access` detected from `access.log`
- [x] At least one violation of type `off_hours_login` detected from `auth.log`
- [x] Every violation dict contains all six schema keys
- [x] Changing `threshold` in config changes the number of `failed_logins` violations
- [x] All 17 tests in `tests/test_detection.py` pass
- [ ] `detect_failed_logins` uses two-pointer sliding window (fix pending)

---

## Phase 3 — Risk Scoring

**Goal:** Assign a likelihood score, impact score, composite risk score, and severity tier to every violation.

### Prerequisite
Apply the Phase 2 fix to `failed_logins.py` and confirm all detection tests pass before starting this phase.

### Files to Create

| File | Purpose |
|------|---------|
| `src/scoring/scorer.py` | Core scoring functions |
| `src/scoring/rules.py` | Lookup tables for likelihood and impact values |
| `tests/test_scoring.py` | Unit tests including all tier boundary cases |

### What Each File Must Do

**scoring/rules.py**

Defines two lookup functions — no hardcoded numbers anywhere else in the codebase.

`get_likelihood(violation: dict) -> int` — returns 1–5 based on these rules:
- `failed_logins`: read count from `detail` field
  - count <= 5: likelihood 2
  - count 6–9: likelihood 3
  - count 10–19: likelihood 4
  - count >= 20 or multi-source: likelihood 5
- `unauthorized_access`: always likelihood 3 (deliberate probe pattern)
- `off_hours_login`: always likelihood 2 (single event, low base frequency)

`get_impact(violation: dict) -> int` — returns 1–5 based on these rules:
- `failed_logins`:
  - username is `root` or `admin`: impact 4
  - any other username: impact 2
- `unauthorized_access`:
  - resource is `/admin`, `/.env`, or `/phpmyadmin`: impact 5
  - resource is `/config` or `/wp-admin`: impact 3
  - any other restricted resource: impact 2
- `off_hours_login`: always impact 3

**scoring/scorer.py**

- `calculate_likelihood(violation: dict) -> int` — calls `get_likelihood`, returns 1–5
- `calculate_impact(violation: dict) -> int` — calls `get_impact`, returns 1–5
- `calculate_score(likelihood: int, impact: int) -> int` — returns `likelihood * impact`
- `assign_severity(score: int, config: dict) -> str` — returns "Low" | "Medium" | "High" | "Critical" using tier ranges from config, never hardcoded
- `score_violation(violation: dict, config: dict) -> dict` — runs all four, returns enriched dict
- `score_all_violations(violations: list[dict], config: dict) -> list[dict]` — applies `score_violation` to entire list

### Enriched Violation Schema (adds to existing six keys)

```python
{
  ...existing six violation keys...,
  "likelihood": int,   # 1–5
  "impact":     int,   # 1–5
  "risk_score": int,   # 1–25, equals likelihood * impact
  "severity":   str    # "Low" | "Medium" | "High" | "Critical"
}
```

### Severity Tier Boundaries (from config — must not be hardcoded)

| Severity | Score Range |
|----------|-------------|
| Low      | 1–4         |
| Medium   | 5–9         |
| High     | 10–16       |
| Critical | 17–25       |

### Verification

```bash
python -c "
import yaml
from src.ingestion.preprocessor import preprocess_log_file
from src.detection.detector import run_detection
from src.scoring.scorer import score_all_violations

config = yaml.safe_load(open('config/config.yaml'))
events = preprocess_log_file('logs/samples/auth.log', 'auth') + \
         preprocess_log_file('logs/samples/access.log', 'web')
violations = run_detection(events, config)
scored = score_all_violations(violations, config)

for v in scored:
    print(f'{v[\"severity\"]:8} | score={v[\"risk_score\"]:2} | L={v[\"likelihood\"]} I={v[\"impact\"]} | {v[\"violation_type\"]}')

assert all('severity' in v for v in scored)
assert all('risk_score' in v for v in scored)
assert all(v['risk_score'] == v['likelihood'] * v['impact'] for v in scored)
print('Phase 3 verification passed.')
"
```

### Acceptance Criteria

- [ ] Every scored violation contains `likelihood`, `impact`, `risk_score`, and `severity`
- [ ] `risk_score` equals `likelihood * impact` for every single violation
- [ ] Score 4 maps to "Low", score 5 maps to "Medium", score 10 maps to "High", score 17 maps to "Critical"
- [ ] Tier boundary tests pass: 4→Low, 5→Medium, 9→Medium, 10→High, 16→High, 17→Critical, 25→Critical
- [ ] `assign_severity` reads tier ranges from config — no hardcoded numbers in scorer.py
- [ ] All tests in `tests/test_scoring.py` pass

### Dependencies
Phase 2 complete including the two-pointer fix. All detection tests must pass before scoring starts.

---

## Phase 4 — Storage Layer

**Goal:** Build the SQLite persistence layer that stores events, violations, and scores across sessions.

### Files to Create

| File | Purpose |
|------|---------|
| `src/storage/db.py` | Database initialization and connection management |
| `src/storage/writer.py` | Insert functions for all three tables |
| `src/storage/reader.py` | Query functions used by the dashboard |
| `tests/test_storage.py` | Unit tests for all write and read operations |

### What Each File Must Do

**db.py**
- `init_db(db_path: str)` — creates the database file and all three tables if they do not exist
- Uses `CREATE TABLE IF NOT EXISTS` — must be safe to call multiple times
- Creates the `data/` directory if it does not exist before creating the db file

Table schemas:

```sql
CREATE TABLE IF NOT EXISTS events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp   TEXT NOT NULL,
  username    TEXT,
  source_ip   TEXT,
  resource    TEXT,
  action      TEXT,
  status_code TEXT,
  log_type    TEXT
);

CREATE TABLE IF NOT EXISTS violations (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  violation_type TEXT NOT NULL,
  timestamp      TEXT NOT NULL,
  username       TEXT,
  source_ip      TEXT,
  resource       TEXT,
  detail         TEXT
);

CREATE TABLE IF NOT EXISTS risk_scores (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  violation_id INTEGER NOT NULL,
  likelihood   INTEGER NOT NULL,
  impact       INTEGER NOT NULL,
  risk_score   INTEGER NOT NULL,
  severity     TEXT NOT NULL,
  FOREIGN KEY (violation_id) REFERENCES violations(id)
);
```

**writer.py**
- `insert_events(events: list[dict], db_path: str)` — batch inserts normalized events; converts datetime to ISO string before insert
- `insert_violation(violation: dict, db_path: str) -> int` — inserts one violation, returns its row `id`
- `insert_risk_score(violation_id: int, scored: dict, db_path: str)` — inserts one risk score row linked to violation_id

**reader.py**
- `get_all_violations_with_scores(db_path: str) -> list[dict]` — JOIN violations + risk_scores, ORDER BY risk_score DESC
- `get_summary_counts(db_path: str) -> dict` — returns:
  ```python
  {
    "total": int,
    "by_type": {"failed_logins": int, "unauthorized_access": int, "off_hours_login": int},
    "by_severity": {"Low": int, "Medium": int, "High": int, "Critical": int}
  }
  ```
- `get_violation_detail(violation_id: int, db_path: str) -> dict` — returns single violation joined with its score
- `get_trend_data(db_path: str, days: int = 7) -> list[dict]` — returns one entry per day for last N days:
  ```python
  [{"date": "2026-05-27", "count": 5}, ...]
  ```

### Verification

```bash
python -c "
import yaml, os
from src.ingestion.preprocessor import preprocess_log_file
from src.detection.detector import run_detection
from src.scoring.scorer import score_all_violations
from src.storage.db import init_db
from src.storage.writer import insert_events, insert_violation, insert_risk_score
from src.storage.reader import get_all_violations_with_scores, get_summary_counts

config = yaml.safe_load(open('config/config.yaml'))
db_path = 'data/test_phase4.db'
if os.path.exists(db_path): os.remove(db_path)

init_db(db_path)
init_db(db_path)  # call twice — must not error

events = preprocess_log_file('logs/samples/auth.log', 'auth') + \
         preprocess_log_file('logs/samples/access.log', 'web')
insert_events(events, db_path)

violations = run_detection(events, config)
scored = score_all_violations(violations, config)
for v in scored:
    vid = insert_violation(v, db_path)
    insert_risk_score(vid, v, db_path)

results = get_all_violations_with_scores(db_path)
summary = get_summary_counts(db_path)
print(f'Stored violations : {len(results)}')
print(f'Summary           : {summary}')

scores = [r['risk_score'] for r in results]
assert scores == sorted(scores, reverse=True), 'Not ordered by risk_score DESC'
assert summary['total'] == len(scored)
print('Phase 4 verification passed.')
os.remove(db_path)
"
```

### Acceptance Criteria

- [ ] `init_db` creates all three tables without error
- [ ] Calling `init_db` twice does not raise an error or duplicate tables
- [ ] `insert_events` batch inserts all events without error
- [ ] `insert_violation` returns the correct integer row id
- [ ] `get_all_violations_with_scores` returns results ordered by `risk_score` descending
- [ ] `get_summary_counts` returns correct totals matching what was inserted
- [ ] `get_trend_data` returns a list of dicts each with `date` and `count` keys
- [ ] `get_violation_detail` returns a single dict for a valid id
- [ ] All tests in `tests/test_storage.py` pass
- [ ] Test uses `data/test_phase4.db` and deletes it after — no test data persists

### Dependencies
Phase 3 complete. Enriched violation dicts with all ten keys must be available.

---

## Phase 5 — Flask Dashboard

**Goal:** Build the web dashboard that reads from the database and presents findings visually.

### Chart Library Decision
Use **Chart.js** loaded from CDN. No install required. Add this to `base.html`:
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

### Files to Create

| File | Purpose |
|------|---------|
| `src/dashboard/app.py` | Flask app — all routes |
| `src/dashboard/templates/base.html` | Base layout with nav and Chart.js CDN link |
| `src/dashboard/templates/index.html` | Overview panel |
| `src/dashboard/templates/violations.html` | Ranked violation list |
| `src/dashboard/templates/detail.html` | Single violation detail |
| `src/dashboard/templates/trend.html` | Trend chart |
| `src/dashboard/static/css/style.css` | Styles and severity colour coding |
| `src/dashboard/static/js/charts.js` | Chart.js initializers |

### Routes

| Route | Template | Data |
|-------|----------|------|
| `GET /` | `index.html` | `get_summary_counts()` |
| `GET /violations` | `violations.html` | `get_all_violations_with_scores()` |
| `GET /violations/<int:id>` | `detail.html` | `get_violation_detail(id)` |
| `GET /trend` | `trend.html` | `get_trend_data()` |
| `GET /export` | — | CSV download |

### app.py Requirements
- Reads `db_path` from config, not hardcoded
- Every route passes data from reader.py — no direct SQL in app.py
- 404 handler returns a plain message for unknown violation ids

### Severity Colour Coding (locked — matches Table 3.3 of IR)

| Severity | Hex Colour |
|----------|-----------|
| Low      | `#28a745` |
| Medium   | `#ffc107` |
| High     | `#dc3545` |
| Critical | `#7b0000` |

Apply as badge background colour on both `violations.html` and `detail.html`.

### index.html Must Show
- Total violation count (large, prominent)
- Count broken down by violation type
- Count broken down by severity
- One Chart.js doughnut chart of severity distribution using the four colours above

### violations.html Must Show
- Table of all violations sorted by risk_score descending (from database, not re-sorted in template)
- Columns: timestamp, type, username, source IP, resource, risk score, severity badge
- Each row is a link to `/violations/<id>`

### detail.html Must Show
- All violation fields
- Likelihood, impact, risk score values
- One plain-language sentence explaining the score, e.g.:
  `"Likelihood 4 × Impact 5 = Risk Score 20 (Critical)"`

### export route
- Queries `get_all_violations_with_scores()`
- Writes CSV to `exports/cybermon_report_YYYY-MM-DD.csv`
- Returns the file as a browser download with `Content-Disposition: attachment`
- CSV headers: `id, violation_type, timestamp, username, source_ip, resource, detail, likelihood, impact, risk_score, severity`

### Verification

```
1. Run: python src/dashboard/app.py
2. Open http://127.0.0.1:5000/ — confirm summary counts and doughnut chart visible
3. Open http://127.0.0.1:5000/violations — confirm table sorted by risk_score descending
4. Click any row — confirm detail view shows score breakdown sentence
5. Open http://127.0.0.1:5000/trend — confirm chart renders with data points
6. Open http://127.0.0.1:5000/export — confirm CSV downloads and opens in Excel
```

### Acceptance Criteria

- [ ] `/` loads without error and shows summary counts and doughnut chart
- [ ] `/violations` table is sorted by risk_score descending
- [ ] Each severity badge uses the correct colour from the table above
- [ ] `/violations/<id>` shows the plain-language score explanation sentence
- [ ] `/trend` renders a line or bar chart with at least one data point
- [ ] `/export` downloads a CSV with correct headers and data
- [ ] Dashboard runs on `127.0.0.1:5000` with no extra setup beyond `pip install -r requirements.txt`
- [ ] No SQL in `app.py` — all data comes through `reader.py` functions
- [ ] No values hardcoded in templates — all data passed from route functions

### Dependencies
Phase 4 complete. Database must be populated with at least one full pipeline run before testing the dashboard.
Run the Phase 4 verification script first to populate the database if needed.

---

## Phase 6 — Integration and UAT

**Goal:** Wire all five components into `main.py` and validate end-to-end behavior with a real pipeline run.

### Files to Modify

| File | Change |
|------|--------|
| `main.py` | Full pipeline replacing the current stub |
| `tests/test_integration.py` | New file — end-to-end test |

### main.py Pipeline (exact order)

```python
1. Load config from config/config.yaml
2. init_db(config['storage']['db_path'])
3. Ingest auth log and web access log (paths from config or CLI args)
4. insert_events(events, db_path)
5. run_detection(events, config) -> violations
6. score_all_violations(violations, config) -> scored
7. For each scored violation: insert_violation, then insert_risk_score
8. Print summary: total events, total violations, breakdown by severity
9. Launch Flask dashboard on configured host:port
```

### test_integration.py Must Test

- Full pipeline runs without error on synthetic logs
- Number of violations in database matches `run_detection` output count
- Dashboard `/` route returns HTTP 200 after pipeline run
- `/export` returns a file with correct CSV headers

### UAT Checklist (manual, done by developer)

- [ ] A non-technical person can read the dashboard without explanation
- [ ] Severity badges are immediately distinguishable by colour
- [ ] The ranked list puts the highest-score violation at the top
- [ ] The export CSV opens correctly in Excel with no encoding issues
- [ ] Running `python main.py` twice does not duplicate data in the database

### Acceptance Criteria

- [ ] `python main.py` completes without error and launches the dashboard
- [ ] `pytest tests/` passes all tests across all six test files
- [ ] No hardcoded paths, thresholds, or magic numbers anywhere in `src/`
- [ ] Running the pipeline twice does not insert duplicate violations
- [ ] UAT checklist above fully signed off

### Dependencies
Phases 1–5 all complete and individually verified.

---

## Full File Tree (end state after Phase 6)

```
cybermon/
├── config/config.yaml
├── data/cybermon.db          (generated — not in repo)
├── exports/                  (generated — not in repo)
├── logs/samples/
│   ├── auth.log
│   └── access.log
├── src/
│   ├── __init__.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── reader.py
│   │   ├── parser.py
│   │   └── preprocessor.py
│   ├── detection/
│   │   ├── __init__.py
│   │   ├── detector.py
│   │   └── rules/
│   │       ├── __init__.py
│   │       ├── failed_logins.py
│   │       ├── unauthorized_access.py
│   │       └── off_hours.py
│   ├── scoring/
│   │   ├── __init__.py
│   │   ├── scorer.py
│   │   └── rules.py
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── db.py
│   │   ├── writer.py
│   │   └── reader.py
│   └── dashboard/
│       ├── __init__.py
│       ├── app.py
│       ├── templates/
│       │   ├── base.html
│       │   ├── index.html
│       │   ├── violations.html
│       │   ├── detail.html
│       │   └── trend.html
│       └── static/
│           ├── css/style.css
│           └── js/charts.js
├── tests/
│   ├── __init__.py
│   ├── test_ingestion.py
│   ├── test_detection.py
│   ├── test_scoring.py
│   ├── test_storage.py
│   └── test_integration.py
├── main.py
├── requirements.txt
├── .gitignore
├── PHASES.md
├── PROGRESS.md
└── README.md
```

---

## Summary Table

| Phase | Key Deliverable | Depends On | Complexity | Status |
|-------|----------------|------------|------------|--------|
| 0 | Project scaffold, config, repo files | Nothing | Low | Complete |
| 1 | Log ingestion + synthetic test data | Phase 0 | Medium | Complete |
| 2 | Three violation detection rules | Phase 1 | Medium | Complete (fix pending) |
| 3 | Likelihood x impact risk scoring | Phase 2 + fix | Low-Medium | Not started |
| 4 | SQLite storage layer (3 tables) | Phase 3 | Medium | Not started |
| 5 | Flask dashboard (5 routes, charts, export) | Phase 4 | High | Not started |
| 6 | Full pipeline integration + UAT | Phases 1-5 | Medium | Not started |
