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

## Phase 0 — Scaffold

**Goal:** Set up the project structure, config system, repo files, and virtual environment.

### Files to Create

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

### config/config.yaml — Required Sections

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

### Folder Tree After Phase 0

```
cybermon/
├── config/config.yaml
├── data/               (empty)
├── exports/            (empty)
├── logs/samples/       (empty)
├── src/
│   ├── __init__.py
│   ├── ingestion/__init__.py
│   ├── detection/__init__.py
│   ├── scoring/__init__.py
│   ├── storage/__init__.py
│   └── dashboard/
│       ├── __init__.py
│       ├── templates/  (empty)
│       └── static/
│           ├── css/    (empty)
│           └── js/     (empty)
├── tests/__init__.py
├── main.py
├── requirements.txt
├── PHASES.md
├── PROGRESS.md
└── README.md
```

### Acceptance Criteria

- [ ] `python -m venv venv` runs without error
- [ ] `venv\Scripts\activate` activates the environment
- [ ] `pip install -r requirements.txt` installs all four packages without error
- [ ] `python main.py` runs and prints config values without error
- [ ] All folders and files above exist
- [ ] `config/config.yaml` loads via `yaml.safe_load()` without error

### Dependencies
None. This is the starting point.

---

## Phase 1 — Log Ingestion and Preprocessing

**Goal:** Build the ingestion module that reads raw log files and outputs normalized event records.

### Files to Create

| File | Purpose |
|------|---------|
| `src/ingestion/reader.py` | Reads raw log files from disk, returns lines |
| `src/ingestion/parser.py` | Parses lines into structured dicts using regex |
| `src/ingestion/preprocessor.py` | Normalizes parsed dicts into a consistent schema |
| `logs/samples/auth.log` | Synthetic Linux auth log (see spec below) |
| `logs/samples/access.log` | Synthetic web access log (see spec below) |
| `tests/test_ingestion.py` | Unit tests for parser and preprocessor |

### What Each File Must Do

**reader.py**
- `read_log_file(filepath: str) -> list[str]` — opens a file, returns non-empty lines as a list
- Raises `FileNotFoundError` with a clear message if the file does not exist
- No parsing logic here — raw lines only

**parser.py**
- `parse_auth_log_line(line: str) -> dict | None` — extracts fields from Linux auth log format using `re`
- `parse_access_log_line(line: str) -> dict | None` — extracts fields from Apache Combined Log Format using `re`
- Returns `None` for lines that do not match (do not crash on unrecognized lines)
- Auth log fields to extract: `timestamp`, `hostname`, `process`, `username`, `source_ip`, `status` (success/failure), `raw`
- Access log fields to extract: `timestamp`, `source_ip`, `method`, `resource`, `status_code`, `raw`

**preprocessor.py**
- `normalize_event(parsed: dict, log_type: str) -> dict` — maps parsed fields to the standard schema
- Standard schema (every event must have all six fields):
  ```
  {
    "timestamp": datetime object,
    "username": str or None,
    "source_ip": str or None,
    "resource": str or None,
    "action": str,        # e.g. "ssh_failed", "http_request"
    "status_code": str    # e.g. "FAILED", "403", "SUCCESS"
  }
  ```
- `preprocess_log_file(filepath: str, log_type: str) -> list[dict]` — calls reader, parser, preprocessor in sequence, returns list of normalized dicts

### Synthetic Test Data

**logs/samples/auth.log** must contain:
- At least 20 lines
- 8 failed SSH login attempts for user `admin` from IP `192.168.1.100` within a 5-minute window
- 3 failed SSH login attempts for user `testuser` spread across 30 minutes
- 2 successful SSH logins (one inside business hours, one at 02:00)
- Lines in standard Linux auth log format:
  `May 27 09:15:32 server sshd[1234]: Failed password for admin from 192.168.1.100 port 22 ssh2`
  `May 27 09:16:01 server sshd[1235]: Accepted password for john from 10.0.0.5 port 22 ssh2`

**logs/samples/access.log** must contain:
- At least 20 lines
- 5 requests returning 403 to `/admin` from IP `10.0.0.50`
- 3 requests returning 401 to `/config` from IP `10.0.0.51`
- 10 normal 200 requests to `/index.html` and `/about`
- Lines in Apache Combined Log Format:
  `10.0.0.50 - - [27/May/2026:10:00:01 +0000] "GET /admin HTTP/1.1" 403 512 "-" "Mozilla/5.0"`

### Verification

```bash
python -c "
from src.ingestion.preprocessor import preprocess_log_file
events = preprocess_log_file('logs/samples/auth.log', 'auth')
print(f'Auth events parsed: {len(events)}')
assert len(events) > 0
events2 = preprocess_log_file('logs/samples/access.log', 'web')
print(f'Web events parsed: {len(events2)}')
assert len(events2) > 0
print('Phase 1 verification passed.')
"
```

```bash
pytest tests/test_ingestion.py -v
```

### Acceptance Criteria

- [ ] `preprocess_log_file('logs/samples/auth.log', 'auth')` returns at least 15 dicts
- [ ] `preprocess_log_file('logs/samples/access.log', 'web')` returns at least 15 dicts
- [ ] Every returned dict contains all six standard schema keys
- [ ] `timestamp` field is a Python `datetime` object, not a string
- [ ] `parse_auth_log_line` returns `None` for a blank or malformed line without raising an exception
- [ ] All tests in `tests/test_ingestion.py` pass

### Dependencies
Phase 0 complete. `config/config.yaml` must be loadable.

---

## Phase 2 — Violation Detection Engine

**Goal:** Build three rule-based detectors that identify policy violations from normalized event records.

### Files to Create

| File | Purpose |
|------|---------|
| `src/detection/detector.py` | Main detection engine — loads config, runs all three rules |
| `src/detection/rules/failed_logins.py` | Rule 1: repeated failed logins threshold rule |
| `src/detection/rules/unauthorized_access.py` | Rule 2: HTTP 403/401 on restricted resources |
| `src/detection/rules/off_hours.py` | Rule 3: successful logins outside business hours |
| `tests/test_detection.py` | Unit tests for all three rules |

### What Each File Must Do

**rules/failed_logins.py**
- `detect_failed_logins(events: list[dict], config: dict) -> list[dict]`
- Filters events where `status_code == "FAILED"`
- Groups by `username` using pandas DataFrame
- Applies rolling time window (from config: `time_window_minutes`)
- Flags username when failure count within the window exceeds threshold (from config: `threshold`)
- Returns list of violation dicts (one per triggered username, not per individual event)

**rules/unauthorized_access.py**
- `detect_unauthorized_access(events: list[dict], config: dict) -> list[dict]`
- Filters events where `status_code` is in `trigger_codes` AND `resource` is in `restricted_resources`
- Both lists come from config
- Returns one violation dict per matching event

**rules/off_hours.py**
- `detect_off_hours_logins(events: list[dict], config: dict) -> list[dict]`
- Filters events where `status_code == "SUCCESS"` (successful logins only)
- Checks `timestamp` against `business_days` and `business_hours_start`/`end` from config
- Flags events that fall outside the defined window
- Returns one violation dict per matching event

**Violation dict schema** (all three rules must return this exact structure):
```python
{
  "violation_type": str,     # "failed_logins" | "unauthorized_access" | "off_hours_login"
  "timestamp": datetime,     # when the violation was detected
  "username": str | None,
  "source_ip": str | None,
  "resource": str | None,
  "detail": str              # human-readable description e.g. "7 failed logins in 5 min"
}
```

**detector.py**
- `run_detection(events: list[dict], config: dict) -> list[dict]`
- Calls all three rule functions
- Combines and returns all violations as a single list
- Does not modify events in place

### Verification

```bash
python -c "
import yaml
from src.ingestion.preprocessor import preprocess_log_file
from src.detection.detector import run_detection

config = yaml.safe_load(open('config/config.yaml'))
auth_events = preprocess_log_file('logs/samples/auth.log', 'auth')
web_events = preprocess_log_file('logs/samples/access.log', 'web')
all_events = auth_events + web_events

violations = run_detection(all_events, config)
print(f'Violations detected: {len(violations)}')
for v in violations:
    print(f'  {v[\"violation_type\"]} | {v[\"detail\"]}')
assert len(violations) > 0
print('Phase 2 verification passed.')
"
```

### Acceptance Criteria

- [ ] `run_detection` returns at least 3 violations from the synthetic logs
- [ ] At least one violation of type `failed_logins` is detected from `auth.log`
- [ ] At least one violation of type `unauthorized_access` is detected from `access.log`
- [ ] At least one violation of type `off_hours_login` is detected from `auth.log`
- [ ] Every violation dict contains all six schema keys
- [ ] Changing `threshold` in config.yaml changes the number of `failed_logins` violations detected
- [ ] All tests in `tests/test_detection.py` pass

### Dependencies
Phase 1 complete. Normalized event dicts with correct schema must be available.

---

## Phase 3 — Risk Scoring

**Goal:** Build the likelihood x impact scoring module that assigns a score and severity tier to each violation.

### Files to Create

| File | Purpose |
|------|---------|
| `src/scoring/scorer.py` | Calculates likelihood, impact, score, and severity tier |
| `src/scoring/rules.py` | Lookup tables mapping violation properties to likelihood and impact values |
| `tests/test_scoring.py` | Unit tests for scoring logic and tier boundaries |

### What Each File Must Do

**scoring/rules.py**
- Defines likelihood lookup: maps violation_type + observed frequency to a likelihood score (1–5)
  - 1 occurrence = 1, 2-4 = 2, multiple in 1 hour = 3, high-frequency in 1 hour = 4, sustained multi-account = 5
- Defines impact lookup: maps violation_type + resource sensitivity to impact score (1–5)
  - failed_logins on standard account = impact 2, on admin account = impact 4
  - unauthorized_access to restricted resource = impact 3, to `/admin` or `/.env` = impact 5
  - off_hours_login default = impact 3
- These values must match Table 3.2 and 3.3 from the IR exactly

**scoring/scorer.py**
- `calculate_likelihood(violation: dict) -> int` — returns 1–5
- `calculate_impact(violation: dict) -> int` — returns 1–5
- `calculate_score(likelihood: int, impact: int) -> int` — returns likelihood * impact
- `assign_severity(score: int, config: dict) -> str` — returns "Low" | "Medium" | "High" | "Critical"
- `score_violation(violation: dict, config: dict) -> dict` — runs all four functions and returns enriched violation dict
- `score_all_violations(violations: list[dict], config: dict) -> list[dict]` — applies `score_violation` to the full list

**Enriched violation dict** (adds to existing keys):
```python
{
  ...existing violation keys...,
  "likelihood": int,
  "impact": int,
  "risk_score": int,
  "severity": str    # "Low" | "Medium" | "High" | "Critical"
}
```

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
    print(f'{v[\"severity\"]:8} | score={v[\"risk_score\"]:2} | {v[\"violation_type\"]}')
assert all('severity' in v for v in scored)
assert all('risk_score' in v for v in scored)
print('Phase 3 verification passed.')
"
```

### Acceptance Criteria

- [ ] Every scored violation contains `likelihood`, `impact`, `risk_score`, and `severity`
- [ ] `risk_score` equals `likelihood * impact` for every violation
- [ ] Score 4 → "Low", score 9 → "Medium", score 10 → "High", score 17 → "Critical"
- [ ] Tier boundaries match config values exactly (no hardcoded numbers in scorer.py)
- [ ] All tests in `tests/test_scoring.py` pass, including boundary tests at 4/5, 9/10, 16/17

### Dependencies
Phase 2 complete. Violation dicts with correct schema must be available.

---

## Phase 4 — Storage Layer

**Goal:** Build the SQLite persistence layer that stores events, violations, and scores across sessions.

### Files to Create

| File | Purpose |
|------|---------|
| `src/storage/db.py` | Database initialization and connection management |
| `src/storage/writer.py` | Insert functions for all three tables |
| `src/storage/reader.py` | Query functions used by the dashboard |
| `tests/test_storage.py` | Unit tests for write and read operations |

### What Each File Must Do

**db.py**
- `init_db(db_path: str)` — creates the database file and all three tables if they do not exist
- Table: `events` — columns: `id`, `timestamp`, `username`, `source_ip`, `resource`, `action`, `status_code`, `log_type`
- Table: `violations` — columns: `id`, `violation_type`, `timestamp`, `username`, `source_ip`, `resource`, `detail`
- Table: `risk_scores` — columns: `id`, `violation_id` (FK), `likelihood`, `impact`, `risk_score`, `severity`
- Must be idempotent — calling `init_db` twice does not error or duplicate tables

**writer.py**
- `insert_events(events: list[dict], db_path: str)` — batch inserts normalized events
- `insert_violation(violation: dict, db_path: str) -> int` — inserts one violation, returns its `id`
- `insert_risk_score(violation_id: int, scored: dict, db_path: str)` — inserts one risk score linked to violation

**reader.py**
- `get_all_violations_with_scores(db_path: str) -> list[dict]` — returns violations joined with risk_scores, ordered by risk_score DESC
- `get_summary_counts(db_path: str) -> dict` — returns `{ "total": int, "by_type": dict, "by_severity": dict }`
- `get_violation_detail(violation_id: int, db_path: str) -> dict` — returns single violation with its score
- `get_trend_data(db_path: str, days: int = 7) -> list[dict]` — returns daily violation counts for the last N days

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
db_path = 'data/test_cybermon.db'
if os.path.exists(db_path): os.remove(db_path)

init_db(db_path)
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
print(f'Stored violations: {len(results)}')
print(f'Summary: {summary}')
assert len(results) > 0
assert summary['total'] > 0
print('Phase 4 verification passed.')
os.remove(db_path)
"
```

### Acceptance Criteria

- [ ] `init_db` creates all three tables without error
- [ ] Calling `init_db` twice does not raise an error
- [ ] `get_all_violations_with_scores` returns results ordered by `risk_score` descending
- [ ] `get_summary_counts` returns correct totals matching inserted data
- [ ] `get_trend_data` returns one entry per day with a `count` field
- [ ] All tests in `tests/test_storage.py` pass
- [ ] No data persists after test cleanup (test uses a separate test db file)

### Dependencies
Phase 3 complete. Scored violation dicts with all enriched fields must be available.

---

## Phase 5 — Flask Dashboard

**Goal:** Build the web dashboard that reads from the database and presents findings visually.

### Decision Point (resolve before starting)
Chart library choice: **Chart.js** (CDN, no install) or **Plotly** (CDN, no install).
Both work. Chart.js is lighter. Plotly has more chart types.
**Recommended: Chart.js.** Confirm before Phase 5 starts.

### Files to Create

| File | Purpose |
|------|---------|
| `src/dashboard/app.py` | Flask application, routes |
| `src/dashboard/templates/base.html` | Base template with nav and Chart.js CDN |
| `src/dashboard/templates/index.html` | Overview panel — summary counts, severity breakdown |
| `src/dashboard/templates/violations.html` | Ranked violation list |
| `src/dashboard/templates/detail.html` | Single violation detail view |
| `src/dashboard/templates/trend.html` | Trend chart — violations over time |
| `src/dashboard/static/css/style.css` | Dashboard styles, severity colour coding |
| `src/dashboard/static/js/charts.js` | Chart.js chart initializers |

### Routes Required

| Route | Template | Data Source |
|-------|----------|-------------|
| `GET /` | `index.html` | `get_summary_counts()` |
| `GET /violations` | `violations.html` | `get_all_violations_with_scores()` |
| `GET /violations/<id>` | `detail.html` | `get_violation_detail(id)` |
| `GET /trend` | `trend.html` | `get_trend_data()` |
| `GET /export` | — | Generates and returns a CSV summary report |

### Severity Colour Coding (must match Table 3.3 from IR)

| Severity | Colour |
|----------|--------|
| Low | Green `#28a745` |
| Medium | Amber `#ffc107` |
| High | Red `#dc3545` |
| Critical | Dark Red `#7b0000` |

### index.html Must Show
- Total violations count
- Count by violation type (failed_logins, unauthorized_access, off_hours_login)
- Count by severity (Low, Medium, High, Critical)
- A Chart.js doughnut or bar chart of severity distribution

### violations.html Must Show
- Table of all violations sorted by risk_score descending
- Each row: timestamp, type, username, source IP, resource, risk score, severity badge (colour-coded)
- Each row links to `/violations/<id>`

### detail.html Must Show
- All violation fields
- Likelihood value, impact value, risk score
- Plain-language explanation of how the score was calculated

### export route
- Returns a CSV file with all violations and scores
- Filename: `cybermon_report_YYYY-MM-DD.csv`
- Saved to `exports/` folder and also triggers browser download

### Verification

```bash
python src/dashboard/app.py
# Then manually verify in browser:
# http://127.0.0.1:5000/           — shows summary counts and chart
# http://127.0.0.1:5000/violations — shows ranked list
# http://127.0.0.1:5000/trend      — shows trend chart
# http://127.0.0.1:5000/export     — downloads CSV
```

### Acceptance Criteria

- [ ] `/` loads without error and displays summary counts
- [ ] `/violations` lists violations ordered by risk_score descending
- [ ] Each severity badge uses the correct colour from Table 3.3
- [ ] `/violations/<id>` shows score breakdown for a single violation
- [ ] `/trend` renders a chart with at least one data point
- [ ] `/export` downloads a CSV file with correct headers
- [ ] Dashboard runs on `127.0.0.1:5000` on a standard Windows laptop with no extra setup
- [ ] No data is hardcoded in templates — all values come from database queries

### Dependencies
Phase 4 complete. Database must contain at least one populated run of events, violations, and scores.

---

## Phase 6 — Integration, Testing, and UAT

**Goal:** Wire all five components into a single `main.py` pipeline and validate end-to-end behavior.

### Files to Modify

| File | Change |
|------|--------|
| `main.py` | Full pipeline: ingest → detect → score → store → launch dashboard |
| `tests/test_integration.py` | End-to-end test using synthetic logs |

### main.py Pipeline Order

1. Load config from `config/config.yaml`
2. Call `init_db(config['storage']['db_path'])`
3. Ingest log files (paths from config or CLI argument)
4. Run detection
5. Score violations
6. Store events, violations, scores
7. Launch Flask dashboard

### UAT

Run the full pipeline against the synthetic logs, then verify:
- A non-technical person can read the dashboard without explanation
- Severity badges are immediately distinguishable
- The ranked list puts the highest-score violation first
- The export CSV opens correctly in Excel

### Acceptance Criteria

- [ ] `python main.py` runs the full pipeline end-to-end without error
- [ ] Dashboard launches automatically after pipeline completes
- [ ] All data in the dashboard matches what the pipeline ingested
- [ ] `pytest tests/` passes all tests across all modules
- [ ] No hardcoded paths, thresholds, or magic numbers anywhere in `src/`
- [ ] UAT sign-off from at least one non-technical user

### Dependencies
Phases 1–5 all complete and individually verified.

---

## Summary Table

| Phase | Key Deliverable | Depends On | Complexity |
|-------|----------------|------------|------------|
| 0 | Project scaffold, config, repo files | Nothing | Low |
| 1 | Log ingestion module + synthetic test data | Phase 0 | Medium |
| 2 | Three violation detection rules | Phase 1 | Medium |
| 3 | Likelihood x impact risk scoring | Phase 2 | Low-Medium |
| 4 | SQLite storage layer (3 tables) | Phase 3 | Medium |
| 5 | Flask dashboard (5 routes, charts, export) | Phase 4 | High |
| 6 | Full pipeline integration + UAT | Phases 1-5 | Medium |
