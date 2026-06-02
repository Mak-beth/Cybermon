# REWORK_PROGRESS.md
# CyberMon — Desktop Application Rework
# Living log. Append only. Never rewrite history.
# Updated after every phase is completed or a decision is made.

---

## How to Use This File

After completing a phase:
1. Copy the phase block template below
2. Fill in every field honestly — failures and workarounds included
3. Commit this file alongside the phase code in the same commit

After making a decision that affects REWORK_PHASES.md:
1. Add a Decision Log entry with the date and reasoning
2. Note if the decision changes any acceptance criterion

---

## Phase Block Template

```
### Phase RN — [Phase Name]
**Status:** Complete | In Progress | Blocked | Failed
**Date Started:**
**Date Completed:**

**Acceptance Criteria Results:**
- [ ] Criterion 1 — pass/fail note
- [ ] Criterion 2 — pass/fail note

**What was built:**

**What didn't work and how it was fixed:**

**Deviations from REWORK_PHASES.md (if any):**

**Test count at end of phase:** [N tests passing]

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
**Impact on REWORK_PHASES.md:**
```

---

## Log

### Phase R0 — Real Log Validation
**Status:** Blocked — one acceptance criterion cannot be met within phase constraints (see Decision Log)
**Date Started:** 2026-06-01
**Date Completed:** —

**Acceptance Criteria Results:**
- [x] SSH_2k.log parse rate ≥ 90% — PASS (structural parse rate 100%; all 2000 lines match sshd format regex)
- [x] Apache_2k.log parse rate ≥ 90% — PASS (structural parse rate 100%; all 2000 lines match Apache error-log format regex)
- [ ] At least one violation of each type detected on real data — BLOCKED (see detail below)
- [x] All 121 original tests passing after any parser fixes — PASS (126 tests passing; count grew during Phases 0–6)
- [x] Parse rates and violation counts recorded here — PASS

**Parse rate detail:**

| File | Total lines | Structurally matched | Events extracted | Structural rate |
|------|-------------|----------------------|-----------------|-----------------|
| SSH_2k.log | 2000 | 2000 | 632 | 100% |
| Apache_2k.log | 2000 | 2000 | 32 | 100% |

Parse rate is measured as structural match (line recognised as a valid log entry by the format regex). The lower event-extraction figures are expected: real SSH logs contain many informational messages (PAM auth checks, disconnect notices, reverse-DNS lookups) that are not authentication events; the Apache file is an error log, not an access log, so most lines are system notices without client request data.

**Violation counts from real logs:**

| Violation type | Count |
|----------------|-------|
| failed_logins | 10 |
| unauthorized_access | 0 |
| off_hours_login | 0 |

**Why two types are absent:**

*unauthorized_access*: The Apache_2k.log from LogHub is an Apache mod_jk **error log**, not an access log. The only lines with a client IP are "Directory index forbidden by rule: /var/www/html/" entries. The resource extracted is `/var/www/html`, which is not in the configured `restricted_resources` list (`/admin`, `/wp-admin`, `/phpmyadmin`, `/config`, `/.env`). This is a data-characteristic mismatch, not a parser bug — the parser correctly extracts the resource from the log line. Fixing this requires adding `/var/www/html` (or a wildcard) to `restricted_resources` in `config/config.yaml`, which R0 prohibits.

*off_hours_login*: SSH_2k.log contains exactly one successful login (`Accepted password` for user `fztu` at 09:32 on Dec 10). Auth logs carry no year. After the timestamp fix (see below), this maps to Dec 10, 2025 — a Wednesday at 09:32, inside business hours (Mon–Fri, 08:00–18:00). The LogHub data was originally collected in 2005 when Dec 10 was a Saturday; with the correct year, an off_hours_login would fire. Without the year embedded in the log format, there is no reliable parser-side fix.

**What was built:**

- Copied REWORK_PHASES.md and REWORK_PROGRESS.md to project root.
- Created `data/real_logs/` directory.
- Downloaded SSH_2k.log (OpenSSH dataset) and Apache_2k.log from logpai/loghub on GitHub.
- Wrote `r0_validate.py` and `r0_detail.py` diagnostic scripts (not part of the application; can be deleted after R0 is signed off).
- Fixed `_parse_auth_timestamp` in `src/ingestion/preprocessor.py`: instead of always using `datetime.now().year` (which placed Dec log entries 6 months in the future), now tries current year first and falls back to previous year if the result would be a future date. This is a correct field-extraction fix within R0 scope.

**What didn't work and how it was fixed:**

- Parser itself had no regex failures — all 4000 lines across both files matched their respective format patterns. No regex changes were needed.
- Timestamp year-defaulting placed SSH log entries in the future. Fixed by trying current year then previous year (see above).
- The two missing violation types are blocked by data characteristics and config constraints, not parser bugs. See Decision Log below.

**Deviations from REWORK_PHASES.md:**

- Test count at baseline was 126, not 121 — this count grew during original Phases 0–6. All 126 pass.
- "At least one violation of each type" criterion cannot be met within R0 constraints. See Decision Log — R0 Violation Coverage for the agreed resolution.

**Test count at end of phase:** 126 passing

**Commit hash:** 8d334c8

---

### Decision — R0 Violation Coverage
**Date:** 2026-06-01
**Context:** Phase R0 requires at least one violation of each type (failed_logins, unauthorized_access, off_hours_login) to be detected from the real log files. The real logs produce only failed_logins (10). The other two types are absent due to data characteristics, not parser bugs:
- Apache_2k.log is an error log; its only client-IP lines reference /var/www/html which is not in the restricted_resources config list.
- SSH_2k.log has one success login at 09:32 on a weekday (Dec 10, 2025), inside business hours.
Neither can be resolved within R0's allowed file changes (src/ingestion/ only; config/config.yaml and src/detection/ locked).

**Options considered:**
1. Accept the limitation: document it here, mark criterion unmet, add /var/www/html to restricted_resources in R1 when config is extended anyway.
2. Use a different Apache log (access format) alongside the error log — but LogHub's Apache dataset is only the error log.
3. Add synthetic log lines to the real-log test run — invalidates the purpose of real-log validation.

**Decision made:** Accept option 1 — proceed to R1. The detection rule for unauthorized_access is correct; the test dataset was an Apache mod_jk error log, not an access log — this is a dataset limitation, not a rule or parser bug. Coverage for unauthorized_access and off_hours_login will be confirmed in R7 using simulate.py with all four severity tiers. /var/www/html will be added to restricted_resources when config.yaml is extended in R2 for agent/server keys.

**Reason:** The parser is correct. The detection rules are correct. The gap is a dataset format mismatch. Blocking R1 for a problem with no parser-level solution is not warranted.

**Impact on REWORK_PHASES.md:** None — the real-log validation goal (confirm parser handles real data) is met. The violation-coverage sub-criterion is documented as a known deviation, not a silent skip.

---

### Phase R1 — Schema Update and Source Host Tagging
**Status:** Complete
**Date Started:** 2026-06-01
**Date Completed:** 2026-06-01

**Acceptance Criteria Results:**
- [x] events table has source_host column — PASS (TEXT NOT NULL DEFAULT 'localhost')
- [x] violations table has source_host column — PASS
- [x] risk_scores table has source_host column — PASS
- [x] All INSERTs write non-null source_host — PASS (verified: LAPTOP-R4I4RA0J in all three tables)
- [x] All SELECTs return source_host — PASS (get_all_violations_with_scores, get_violation_detail both include v.source_host)
- [x] migrate_db.py runs without error — PASS (ran against data/cybermon.db; all three tables migrated)
- [x] All 121 original tests passing — PASS (126 tests passing)
- [x] python main.py runs end-to-end in standalone mode — PASS (70 events, 13 violations, all four severity tiers present)

**What was built:**
- `src/storage/db.py`: added `source_host TEXT NOT NULL DEFAULT 'localhost'` to CREATE TABLE for events, violations, risk_scores.
- `src/ingestion/preprocessor.py`: added `"source_host": socket.gethostname()` to both auth and web event dicts in normalize_event().
- `src/storage/writer.py`: added source_host to INSERT in insert_events(), insert_violation(), insert_risk_score(). Each falls back to socket.gethostname() if source_host is not in the input dict (detection rules don't add it; network mode will supply it in R2).
- `src/storage/reader.py`: added v.source_host to the SELECT in get_all_violations_with_scores() and get_violation_detail().
- `tests/test_storage.py`: added source_host to required keys set; updated raw SQL INSERT in test_get_trend_by_hour_today_captures_todays_violations to include source_host.
- `migrate_db.py`: new file — uses PRAGMA table_info to check and ALTER TABLE ADD COLUMN on existing databases upgrading from the original build.

**What didn't work and how it was fixed:**
- First test run failed with OperationalError on data/cybermon.db — the existing database was created before R1 changes, so init_db (CREATE TABLE IF NOT EXISTS) left the old schema untouched. Fix: ran migrate_db.py against data/cybermon.db to add source_host columns to all three tables. All 126 tests passed on the second run.

**Deviations from REWORK_PHASES.md:**
- Test count remains 126 (not 121) — grew during Phases 0–6.
- source_host is not added to violation dicts by detection rules (src/detection/ is locked). insert_violation() and insert_risk_score() fall back to socket.gethostname(). This is correct for standalone mode; R2 will supply source_host from the agent POST body for network mode.

**Test count at end of phase:** 126 passing

**Commit hash:** 2acdf0e

---

### Phase R2 — Agent and Ingest Endpoint
**Status:** Complete
**Date Started:** 2026-06-01
**Date Completed:** 2026-06-01

**Acceptance Criteria Results:**
- [x] Agent tails a file and POSTs new lines locally — PASS (test_agent_picks_up_new_lines_from_file; functional end-to-end confirmed)
- [x] Ingest endpoint receives POST and runs pipeline — PASS (test_pipeline_end_to_end_post_to_stored_violation)
- [x] Violations from agent POST have correct source_host in database — PASS (test_source_host_stored_from_post_body: "remote-machine-X" written to violations table)
- [x] Ingest endpoint returns HTTP 400 on malformed body — PASS (5 separate 400 tests: missing host, missing lines, not JSON, empty body, lines not a list)
- [x] Agent retries 3 times on connection failure — PASS (test_retry_fires_on_connection_error: mock called exactly 3 times)
- [x] All new tests passing — PASS (20 new tests: 8 agent, 12 endpoint)
- [x] All 121 original tests passing — PASS (126 original tests all passing)
- [x] mode: standalone leaves original behaviour unchanged — PASS (all integration and live tests pass; ingest server not started in standalone mode)

**Simulated network test result:** Covered by automated tests. Manual two-terminal test (python main.py with mode:network + python agent_main.py) is available for UAT in R8.

**What was built:**

Part A — Agent:
- `src/agent/__init__.py`: package marker
- `src/agent/agent.py`: CyberMonAgent class — seeks to end of file on open, drains all available lines in each poll cycle, POSTs batches as `{"host": host_id, "lines": [...]}`, retries up to retry_attempts times with retry_delay_seconds between attempts, handles missing log file gracefully
- `agent_main.py`: entry point; reads/creates agent_config.yaml; sets up file+stdout logging to agent.log; graceful KeyboardInterrupt shutdown

Part B — Ingest Endpoint:
- `server/__init__.py`: package marker
- `server/ingest_endpoint.py`: fresh Flask(__name__) app (separate from dashboard); POST /ingest route; validates JSON body; runs each line through parser → normalize_event → detection → scoring → storage; sets source_host from POST body host field; returns {"received": N, "violations_detected": M}; returns 400 for any validation failure
- `main.py`: added _start_ingest_server() — starts ingest_app on a daemon thread on port 5001, then sleeps 1 second before dashboard starts; only called when config["mode"] == "network"

Part C — Config:
- `config/config.yaml`: added mode, server, and agent blocks; added /var/www/html to restricted_resources (R0 Decision Log commitment)
- `requirements.txt`: added requests
- `.gitignore`: added agent_config.yaml and agent.log

Part D — Tests:
- `tests/test_agent.py`: 8 tests covering JSON structure, URL, return value, retry on ConnectionError, retry on non-200, success on second attempt, missing file handling, real file tail
- `tests/test_ingest_endpoint.py`: 12 tests covering empty lines, unparseable lines, received count, all 5 malformed-body variants, source_host in violations table, source_host in events table, full SSH end-to-end, web log end-to-end

**What didn't work and how it was fixed:**
- `requests` not installed in venv — requirements.txt was updated but pip install was needed. Ran `pip install requests`.

**Deviations from REWORK_PHASES.md:**
- Ingest endpoint uses a fresh `Flask(__name__)` instance (not a Blueprint registered on an existing app), per explicit user instruction. This is strictly better: the ingest server is fully independent and survives when the dashboard is replaced in R3.
- `_load_config()` is called per-request inside the handler (not at module load time) to support test isolation via `unittest.mock.patch`.

**Test count at end of phase:** 146 passing (126 original + 20 new)

**Commit hash:** 7c88e56

---

### Phase R3 — PyQt6 Main Window and Violations Table
**Status:** Complete
**Date Started:** 2026-06-01
**Date Completed:** 2026-06-01

**Acceptance Criteria Results:**
- [x] python main.py launches native desktop window (no browser) — PASS (QApplication + MainWindow; Flask app.run removed from standalone path)
- [x] Sidebar navigation switches panels without error — PASS (QStackedWidget + QButtonGroup; 5 nav items, index switching tested manually)
- [x] Violations table shows all violations from database — PASS (get_all_violations() returns 13 rows from live DB; all displayed in QTableWidget)
- [x] Violations sorted by risk score descending — PASS (sortItems(_COL_SCORE, DescendingOrder) after populate; sorting also enabled by clicking headers)
- [x] Severity badges colour-coded for all four tiers — PASS (Low: green/#14532d, Medium: amber/#78350f, High: red/#7f1d1d, Critical: dark-red/white)
- [x] Host filter dropdown shows unique source_host values — PASS (get_unique_hosts() populates QComboBox; "All Hosts" always first)
- [x] Host filter updates table correctly — PASS (_on_filter_changed triggers _reload_table with host_filter arg)
- [x] Refresh button re-queries and updates — PASS (refresh() reloads both dropdown and table from DB)
- [x] Row click does not crash — PASS (_on_row_clicked extracts violation_id from UserRole data; no-op placeholder for R5)
- [x] All 121 original tests passing — PASS (146/146, all green; Qt imports inside main() so tests never touch Qt)
- [x] Window usable at 1200x750 — PASS (setMinimumSize(1200, 750); column resizing: Type and Action stretch, others ResizeToContents)

**What was built:**

Part A — Dependencies:
- `requirements.txt`: added PyQt6>=6.6.0 and PyQtGraph>=0.13.0; both installed to venv

Part B — Entry point:
- `main.py`: removed --live argparse argument and its entire Flask SSE branch; removed Flask app.run() from standalone path; removed use_reloader; added sys import; added lazy PyQt6 imports inside main() so test imports of run_pipeline never touch Qt; added QApplication + MainWindow launch; network mode _start_ingest_server() unchanged
- `start.bat`: removed --live flag (was: `main.py --live --auth-log ...`; now: `main.py --auth-log ...`)

Part C — Main window:
- `src/gui/__init__.py`: package marker
- `src/gui/main_window.py`: MainWindow(QMainWindow) — 1200×750 minimum, resizable; 200px dark sidebar (#1e1e2e) with QButtonGroup-managed _SidebarButton items; active item gets 4px #7c3aed left border via stylesheet; QStackedWidget content area; _switch_to(index) swaps panels; shield icon rendered programmatically with QPainter; ViolationsTable at index 1 (Violations); placeholder QLabels for Overview/Live Feed/Trend/Settings

Part D — Violations table:
- `src/gui/violations_table.py`: ViolationsTable(QWidget) — top bar with QComboBox host filter and refresh QPushButton; QTableWidget with 6 columns; non-editable items; alternating row colours; sortable by clicking headers; severity badge cells use QColor background/foreground; risk score stored as int via DisplayRole for correct numeric sort; row click handler extracts violation_id (placeholder for R5)

Part E — Data access layer:
- `src/gui/data_access.py`: get_all_violations(host_filter), get_violation_by_id(id), get_summary_counts(), get_unique_hosts(); all load config.yaml for db_path; all use sqlite3.Row for dict-style access; get_all_violations and get_violation_by_id append recommended_action from RECOMMENDED_ACTIONS map; smoke-tested: returns 13 rows with all expected keys against live database

**What didn't work and how it was fixed:**
- No failures during implementation. All 146 tests passed first run after each part.

**Deviations from REWORK_PHASES.md:**
- spec listed Part E (data access) before Part D (violations table), but Part E was implemented first as a dependency of Part D. Test count reported after D+E together as per spec's "Part D" step.
- PyQt6 imports are inside main() rather than at file top — necessary to prevent Qt import at test-collection time.

**Test count at end of phase:** 146 passing (no new tests in R3 — GUI code is not unit-tested at this stage per spec)

**Commit hash:** (pending)

---

### Phase R4 — Overview Dashboard and Charts
**Status:** Not started
**Date Started:**
**Date Completed:**

**Acceptance Criteria Results:**
- [ ] Overview panel shows correct total violation count
- [ ] Critical, High, Medium+Low counts correct
- [ ] Breakdown bars correct proportions
- [ ] Doughnut chart correctly proportioned and colour-coded
- [ ] Trend chart correct for today by hour
- [ ] Trend chart correct for last 7 days
- [ ] Auto-refresh every 30 seconds
- [ ] Host filter on overview works
- [ ] All 121 original tests passing

**What was built:**

**What didn't work and how it was fixed:**

**Deviations from REWORK_PHASES.md (if any):**

**Test count at end of phase:**

**Commit hash:**

---

### Phase R5 — Violation Detail View and Live Feed
**Status:** Not started
**Date Started:**
**Date Completed:**

**Acceptance Criteria Results:**
- [ ] Clicking row opens detail panel with correct data
- [ ] Score breakdown shows correct L, I, and product
- [ ] Recommended action matches severity tier exactly
- [ ] Log excerpt matches raw line in database
- [ ] Live feed shows new violations within 5 seconds
- [ ] Live feed does not duplicate entries
- [ ] Pause button works correctly
- [ ] Export button copies summary to clipboard
- [ ] All 121 original tests passing

**What was built:**

**What didn't work and how it was fixed:**

**Deviations from REWORK_PHASES.md (if any):**

**Test count at end of phase:**

**Commit hash:**

---

### Phase R6 — Setup Wizard
**Status:** Not started
**Date Started:**
**Date Completed:**

**Acceptance Criteria Results:**
- [ ] First launch (no config) shows wizard
- [ ] Standalone mode shows Page 2a
- [ ] Network mode shows Page 2b
- [ ] Test paths button identifies missing files
- [ ] Wizard writes correct config.yaml
- [ ] setup_complete: true written on completion
- [ ] Second launch skips wizard
- [ ] Settings panel shows current config
- [ ] Save from settings updates config.yaml
- [ ] Re-run wizard resets setup_complete
- [ ] All wizard tests passing
- [ ] All 121 original tests passing

**What was built:**

**What didn't work and how it was fixed:**

**Deviations from REWORK_PHASES.md (if any):**

**Test count at end of phase:**

**Commit hash:**

---

### Phase R7 — Export, Error Handling, Empty States, Polish
**Status:** Not started
**Date Started:**
**Date Completed:**

**Acceptance Criteria Results:**
- [ ] CSV export produces correct file
- [ ] File save dialog works
- [ ] Missing log file shows warning banner not crash
- [ ] Empty database shows friendly empty state
- [ ] simulate.py produces all four severity tiers
- [ ] All four tiers visible with correct colours
- [ ] Old Flask dashboard removed, app starts cleanly
- [ ] 140+ tests passing

**What was built:**

**What didn't work and how it was fixed:**

**Deviations from REWORK_PHASES.md (if any):**

**Test count at end of phase:**

**Commit hash:**

---

### Phase R8 — User Acceptance Testing
**Status:** Not started
**Date Started:**
**Date Completed:**

**Participant 1 (Standalone):**
- Task completion: 
- Points of confusion:
- Time to complete:

**Participant 2 (Standalone):**
- Task completion:
- Points of confusion:
- Time to complete:

**Participant 3 (Network):**
- Task completion:
- Points of confusion:
- Time to complete:

**UAT Pass Criteria Results:**
- [ ] Both standalone participants complete all 8 tasks without asking for help
- [ ] Network participant completes tasks 1–7 without asking for help
- [ ] No participant confused by the same element twice
- [ ] Average time under 15 minutes

**Fixes applied after UAT:**

**Test count after UAT fixes:**

**Commit hash:**

---

### Phase R9 — PyInstaller Packaging
**Status:** Not started
**Date Started:**
**Date Completed:**

**Acceptance Criteria Results:**
- [ ] CyberMon.exe launches without Python installed
- [ ] CyberMon.exe shows wizard on first launch
- [ ] CyberMon.exe shows dashboard after wizard
- [ ] CyberMonAgent.exe launches and tails log without Python
- [ ] Both exes under 150MB
- [ ] No console window appears
- [ ] Clean machine test passes

**Build commands used:**

**Clean machine test result:**

**What didn't work and how it was fixed:**

**Commit hash:**

---

### Phase R10 — IR Update and GitHub Polish
**Status:** Not started
**Date Started:**
**Date Completed:**

**Acceptance Criteria Results:**
- [ ] IR Chapter 3 architecture reflects dual-mode system
- [ ] IR Chapter 4 updated achievements include rework
- [ ] NFR-05 status updated in IR
- [ ] README.md clear for non-developer
- [ ] README.md setup instructions correct
- [ ] CHANGELOG.md documents both versions

**Commit hash:**

---
