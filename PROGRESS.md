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
