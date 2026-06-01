# REWORK_PHASES.md
# CyberMon — Desktop Application Rework
# Static reference document. Created once. Never edited after rework begins.
# All phases, acceptance criteria, file trees, and sequencing rationale live here.
# Add to repo root alongside REWORK_PROGRESS.md before starting Phase R0.

---

## What This Rework Is

The original CyberMon system (Phases 0–6) produced a working Flask web application
running in a browser. That system is complete and tested (121 tests passing, all 10 FRs
and 5 NFRs met in code).

This rework does the following:
1. Replaces the Flask/browser frontend with a native PyQt6 desktop GUI
2. Adds dual-mode deployment — standalone (single machine) or network (central server + agents)
3. Adds a guided 3-screen setup wizard that runs on first launch
4. Adds a lightweight agent (CyberMonAgent) that ships logs from remote machines to the server
5. Adds source_host tagging so every violation is attributed to the machine it came from
6. Packages the finished application as two distributable .exe files via PyInstaller

The backend pipeline — ingestion, detection, scoring, SQLite storage — is UNCHANGED.
Every rework phase builds on top of a stable, tested foundation.

---

## What Does NOT Change

The following components are locked. Claude Code must not modify them unless a phase
explicitly says otherwise:

- `src/ingestion/` — log reader and parser
- `src/detection/` — all three violation rules
- `src/scoring/` — likelihood × impact model
- `src/storage/` — SQLite operations (schema changes are scoped to Phase R1 only)
- `config/config.yaml` — structure extended but existing keys preserved
- `tests/` — all 121 existing tests must pass at the end of every phase

---

## Sequencing Rationale

The rework follows the same backend-first principle as the original build.
The GUI cannot show data that does not exist. The agent cannot send data that the
server cannot receive. The wizard cannot configure a system that is not yet built.

Correct order:
- R0: Real log validation — confirm the parser works on real-world data before
      building anything new on top of it
- R1: Schema update — source_host tagging touches storage and ingestion; must be done
      before detection or GUI phases so every downstream component uses the new schema
- R2: Agent + ingest endpoint — network mode backend must exist before the GUI can
      offer network mode as an option in the wizard
- R3: Main window + violations table — first PyQt6 screen; wires directly to the
      existing database; no Flask dependency
- R4: Overview dashboard + charts — builds on R3's main window
- R5: Violation detail view + live feed — builds on R3 and R4
- R6: Setup wizard — can only be built once the full app exists behind it; the wizard
      launches into a complete system, not a partial one
- R7: Export, error handling, empty states — polish layer; requires all views to exist
- R8: UAT — requires complete system; must be done before packaging
- R9: PyInstaller packaging — final step; requires everything above to be working
- R10: IR update + GitHub polish — documentation only; no code changes

---

## Rework File Tree (target state after R9)

```
cybermon/
├── REWORK_PHASES.md          ← this file
├── REWORK_PROGRESS.md        ← living log, updated after each phase
├── PHASES.md                 ← original build reference (do not edit)
├── PROGRESS.md               ← original build log (do not edit)
├── config/
│   └── config.yaml           ← extended with agent_port, business_hours, host_id
├── src/
│   ├── ingestion/            ← UNCHANGED
│   ├── detection/            ← UNCHANGED
│   ├── scoring/              ← UNCHANGED
│   ├── storage/              ← schema updated in R1 only
│   ├── gui/
│   │   ├── __init__.py
│   │   ├── main_window.py    ← QMainWindow, sidebar navigation
│   │   ├── overview_panel.py ← summary counts, severity chart
│   │   ├── violations_table.py ← sortable table, colour-coded badges
│   │   ├── detail_panel.py   ← single violation breakdown + recommended action
│   │   ├── live_feed.py      ← real-time violation stream
│   │   ├── trend_panel.py    ← violations by hour and by day
│   │   └── wizard.py         ← 3-screen setup flow
│   └── agent/
│       ├── __init__.py
│       └── agent.py          ← log tailer + HTTP POST to /ingest
├── server/
│   └── ingest_endpoint.py    ← Flask route /ingest for network mode
├── tests/
│   ├── [all 121 existing tests — unchanged]
│   ├── test_agent.py         ← R2
│   ├── test_ingest_endpoint.py ← R2
│   ├── test_gui_overview.py  ← R4
│   └── test_wizard.py        ← R6
├── dist/
│   ├── CyberMon.exe          ← built in R9
│   └── CyberMonAgent.exe     ← built in R9
├── build/
│   ├── cybermon.spec         ← PyInstaller spec for main app
│   └── agent.spec            ← PyInstaller spec for agent
├── simulate.py               ← UNCHANGED
├── main.py                   ← updated in R3 to launch PyQt6 instead of Flask
├── agent_main.py             ← entry point for CyberMonAgent, created in R2
├── requirements.txt          ← updated in R3 to add PyQt6, PyQtGraph, requests
└── README.md                 ← updated in R10
```

---

## Phase R0 — Real Log Validation

**Goal:** Confirm the existing parser correctly handles real-world log files before
building any new components on top of it. This phase produces no new features.
It closes the known gap identified at end of the original build.

**Why first:** If the parser fails on real logs, everything built above it is suspect.
Fix the foundation before adding floors.

**Inputs required before starting:**
- SSH_2k.log from LogHub (Loghub-2.0 repository, HDFS/SSH dataset)
- Apache_2k.log from LogHub (Apache access log dataset)
- Both files placed in `data/real_logs/` (create folder if not exists)

**What Claude Code must do:**
1. Run the existing ingestion pipeline against SSH_2k.log
2. Print parse rate: lines attempted vs lines successfully parsed
3. Run the existing ingestion pipeline against Apache_2k.log
4. Print parse rate for Apache log
5. Run all three detection rules against the parsed real log data
6. Print how many violations of each type were detected
7. Fix any regex patterns in `src/ingestion/` that cause parse failures
8. Do NOT change detection logic, scoring logic, or schema during this phase
9. Update `REWORK_PROGRESS.md` with parse rates and violation counts

**Acceptance Criteria:**
- [ ] SSH_2k.log parse rate is 90% or above (≥1800 of 2000 lines parsed)
- [ ] Apache_2k.log parse rate is 90% or above
- [ ] At least one violation of each type is detected across both real log files
- [ ] All 121 existing tests still pass after any parser fixes
- [ ] Parse rates and violation counts recorded in REWORK_PROGRESS.md

**Files that may change in this phase:**
- `src/ingestion/log_reader.py` — regex fixes only
- `src/ingestion/preprocessor.py` — field extraction fixes only
- `REWORK_PROGRESS.md` — log entry added
- Nothing else

**Files that must NOT change:**
- `src/detection/`
- `src/scoring/`
- `src/storage/`
- `config/config.yaml`
- All test files

---

## Phase R1 — Schema Update and Source Host Tagging

**Goal:** Add source_host to the database schema so every event and violation is
attributed to the machine it came from. This enables the multi-machine dashboard
view and is required by network mode.

**Why before the GUI:** Every downstream component — the agent, the ingest endpoint,
the dashboard tables, the detail view — needs source_host to exist in the database.
Adding it later forces a migration and breaks existing queries.

**Dependency:** Phase R0 must be complete and all 121 tests passing.

**What Claude Code must do:**
1. Add `source_host TEXT NOT NULL DEFAULT 'localhost'` to the `events` table
2. Add `source_host TEXT NOT NULL DEFAULT 'localhost'` to the `violations` table
3. Add `source_host TEXT NOT NULL DEFAULT 'localhost'` to the `risk_scores` table
4. Update `src/storage/db.py` CREATE TABLE statements to include source_host
5. Update `src/ingestion/` to pass hostname into the event dict
   - In standalone mode: use `socket.gethostname()` to get local hostname
   - In network mode (R2): source_host will come from the agent POST body
6. Update all INSERT statements in storage to write source_host
7. Update all SELECT queries to return source_host
8. Update all 121 existing tests to pass with the new schema
   - Tests that create events must include source_host
   - Tests that query events must expect source_host in results
9. Write a one-time migration script `migrate_db.py` that adds source_host
   columns to an existing database for users upgrading from the original build
10. Confirm all 121 tests pass after changes

**Acceptance Criteria:**
- [ ] `events` table has source_host column
- [ ] `violations` table has source_host column
- [ ] `risk_scores` table has source_host column
- [ ] All INSERT operations write a non-null source_host value
- [ ] All SELECT operations return source_host in results
- [ ] `migrate_db.py` runs without error on the existing database
- [ ] All 121 existing tests pass with no modifications to test logic
- [ ] `python main.py` still runs end-to-end in standalone mode

**Files that may change in this phase:**
- `src/storage/db.py`
- `src/ingestion/log_reader.py`
- `src/ingestion/preprocessor.py`
- `tests/` — schema-related updates only
- `migrate_db.py` — new file
- `REWORK_PROGRESS.md`

**Files that must NOT change:**
- `src/detection/`
- `src/scoring/`
- `config/config.yaml`
- Any file outside src/storage and src/ingestion

---

## Phase R2 — Agent and Ingest Endpoint

**Goal:** Build the two new components that enable network mode — a lightweight agent
script that tails a log file and POSTs new lines to the server, and a Flask endpoint
on the server that receives those lines and runs them through the existing pipeline.

**Why before the GUI:** The wizard (R6) must be able to offer network mode as a real
option, not a placeholder. The overview dashboard (R4) must be able to show violations
from multiple machines. Both require this backend to exist and be testable first.

**Dependency:** Phase R1 must be complete.

**What Claude Code must do:**

PART A — Agent (agent.py and agent_main.py):
1. Create `src/agent/agent.py` with the following behaviour:
   - Accepts server IP, server port, log file path, and host identifier via config
   - Tails the specified log file continuously using a seek pointer
   - When new lines appear, POSTs them to `http://{server_ip}:{port}/ingest`
   - POST body is JSON: `{"host": "hostname", "lines": ["line1", "line2", ...]}`
   - Retries failed POSTs up to 3 times with a 2-second delay
   - Logs all activity to `agent.log` in the same directory
   - Graceful shutdown on KeyboardInterrupt
   - No dependencies beyond Python standard library + `requests`
2. Create `agent_main.py` in repo root as the entry point for CyberMonAgent.exe
   - Reads `agent_config.yaml` for server IP, port, log path, host ID
   - Creates `agent_config.yaml` with defaults if it does not exist
   - Prints clear status messages: connected, sending, error

PART B — Ingest endpoint (server/ingest_endpoint.py):
1. Create `server/ingest_endpoint.py` with a Flask Blueprint:
   - Route: POST `/ingest`
   - Accepts JSON body: `{"host": "hostname", "lines": ["line1", "line2", ...]}`
   - Passes each line through the existing ingestion pipeline
   - Sets source_host from the "host" field in the POST body
   - Returns JSON: `{"received": N, "violations_detected": M}`
   - Returns HTTP 400 if body is malformed
2. Register the Blueprint in `main.py` when running in network mode
3. Network mode is activated by `config.yaml` key `mode: network`
   - Default is `mode: standalone`

PART C — Config extension:
1. Add to `config/config.yaml`:
   ```yaml
   mode: standalone          # standalone | network
   server:
     host: 0.0.0.0
     port: 5001              # ingest endpoint port (separate from dashboard)
   agent:
     server_ip: 127.0.0.1
     server_port: 5001
     log_path: logs/auth.log
     host_id: agent-machine-1
     retry_attempts: 3
     retry_delay_seconds: 2
   ```

PART D — Tests:
1. Create `tests/test_agent.py`:
   - Test POST sends correct JSON structure
   - Test retry logic fires on connection failure
   - Test agent stops tailing when log file does not exist
2. Create `tests/test_ingest_endpoint.py`:
   - Test valid POST returns 200 with correct JSON response
   - Test malformed POST returns 400
   - Test source_host is correctly written to database from POST body
   - Test pipeline runs end-to-end from POST to stored violation

**Acceptance Criteria:**
- [ ] Agent tails a file and POSTs new lines when run locally
- [ ] Ingest endpoint receives POST and runs pipeline without error
- [ ] Violations from agent POST appear in SQLite with correct source_host
- [ ] Ingest endpoint returns HTTP 400 on malformed body
- [ ] Agent retries 3 times on connection failure then logs error and continues
- [ ] All new tests pass
- [ ] All 121 original tests still pass
- [ ] `mode: standalone` in config.yaml leaves all original behaviour unchanged

**Simulated network test (you run this manually, not CC):**
- Run `python main.py` in one terminal (server mode)
- Run `python agent_main.py` in a second terminal
- Append a line to the watched log file manually
- Confirm violation appears in database within 5 seconds

**Files created in this phase:**
- `src/agent/__init__.py`
- `src/agent/agent.py`
- `agent_main.py`
- `server/__init__.py`
- `server/ingest_endpoint.py`
- `tests/test_agent.py`
- `tests/test_ingest_endpoint.py`
- `agent_config.yaml` (default, gitignored)

**Files modified in this phase:**
- `config/config.yaml`
- `main.py` — register ingest Blueprint when mode is network
- `requirements.txt` — add `requests`
- `REWORK_PROGRESS.md`

---

## Phase R3 — PyQt6 Main Window and Violations Table

**Goal:** Replace Flask as the frontend. Build the main application window with a
sidebar for navigation and the violations table as the first content panel. This
is the largest architectural change in the rework. All other GUI phases build on top
of what is created here.

**Dependency:** Phase R1 must be complete (source_host in schema).
Phase R2 does not need to be complete before R3 begins but R2 must be complete
before the source host filter (R4) is built.

**What Claude Code must do:**

PART A — Dependencies:
1. Add to `requirements.txt`:
   - `PyQt6>=6.6.0`
   - `PyQtGraph>=0.13.0`
2. Confirm `pip install -r requirements.txt` completes without error

PART B — Application entry point:
1. Update `main.py`:
   - In standalone mode: launch `QApplication` and show `MainWindow`
   - Flask is no longer launched for standalone mode
   - Network mode still starts the Flask ingest endpoint as a background thread
     before launching the Qt window
   - Remove all Flask `app.run()` calls from standalone path

PART C — Main window (src/gui/main_window.py):
1. `MainWindow(QMainWindow)`:
   - Fixed window size: 1200 × 750 minimum, resizable
   - Left sidebar: 200px wide, flat background, no border
   - Sidebar items (top to bottom): Overview, Violations, Live Feed, Trend, Settings
   - Active item is highlighted with a left accent bar (4px, purple-ish)
   - Content area: fills remaining space to the right of sidebar
   - Switching sidebar items swaps the content panel (QStackedWidget)
   - Window title: "CyberMon — Security Monitoring"
   - Application icon: use a shield SVG rendered as QIcon (create simple one)
   - No menu bar. No toolbar. Clean and minimal.

PART D — Violations table (src/gui/violations_table.py):
1. `ViolationsTable(QWidget)`:
   - Fetches all violations from SQLite ordered by risk_score DESC
   - Displays in a QTableWidget with columns:
     - Severity (colour-coded badge: green/amber/red/dark-red)
     - Risk Score (number, right-aligned)
     - Violation Type (plain text)
     - Source Host (plain text)
     - Timestamp (formatted: YYYY-MM-DD HH:MM:SS)
     - Recommended Action (short text, truncated if long)
   - Clicking a row opens the detail panel for that violation (placeholder for R5)
   - Refresh button in top-right of panel — re-queries database
   - Filter dropdown: All Hosts | [list of unique source_hosts from database]
   - Rows are non-editable
   - Alternating row colours for readability
   - Table is sortable by clicking column headers
2. Severity badge rendering:
   - Low: green background, dark green text
   - Medium: amber background, dark amber text
   - High: red background, dark red text
   - Critical: dark red background, white text

PART E — Data access layer:
1. Create `src/gui/data_access.py`:
   - `get_all_violations(host_filter=None)` — returns list of dicts
   - `get_violation_by_id(violation_id)` — returns single dict
   - `get_summary_counts()` — returns total, by_type, by_severity dicts
   - `get_unique_hosts()` — returns list of source_host strings
   - All functions read from SQLite directly using existing db.py connection

**Acceptance Criteria:**
- [ ] `python main.py` launches a native desktop window (no browser opens)
- [ ] Sidebar navigation switches between panels without error
- [ ] Violations table shows all violations from the database
- [ ] Violations are sorted by risk score descending by default
- [ ] Severity badges are colour-coded correctly for all four tiers
- [ ] Host filter dropdown shows all unique source_host values
- [ ] Selecting a host filter shows only violations from that host
- [ ] Refresh button re-queries and updates the table
- [ ] Clicking a row does not crash (detail panel placeholder acceptable at this stage)
- [ ] All 121 original tests still pass
- [ ] Window is usable at 1200×750 with no clipped text or overlapping elements

**Files created in this phase:**
- `src/gui/__init__.py`
- `src/gui/main_window.py`
- `src/gui/violations_table.py`
- `src/gui/data_access.py`

**Files modified in this phase:**
- `main.py`
- `requirements.txt`
- `REWORK_PROGRESS.md`

**Note on Flask:** Flask is not removed from the project in this phase. It remains in
`requirements.txt` and is still used by the ingest endpoint in network mode. Only the
dashboard routes (`/`, `/violations`, `/live`, `/trend`, `/export`) are superseded.
Remove the old Flask dashboard files in R7 after all GUI panels are confirmed working.

---

## Phase R4 — Overview Dashboard and Charts

**Goal:** Build the overview panel and embed charts using PyQtGraph. This is the
first panel the user sees after the wizard completes.

**Dependency:** Phase R3 must be complete and passing.

**What Claude Code must do:**

PART A — Overview panel (src/gui/overview_panel.py):
1. `OverviewPanel(QWidget)`:
   - Four metric cards at the top (use QFrame):
     - Total Violations (integer)
     - Critical (count, dark red accent)
     - High (count, red accent)
     - Medium + Low (combined count, amber accent)
   - Violation breakdown by type below the cards (three rows):
     - Repeated Failed Logins: count + horizontal bar
     - Unauthorized Access: count + horizontal bar
     - Off-Hours Logins: count + horizontal bar
   - Doughnut-style chart on the right side showing severity distribution
     - Built with PyQtGraph using a pie chart or a custom QWidget painter
     - Four segments: Low (green), Medium (amber), High (red), Critical (dark red)
   - Auto-refreshes every 30 seconds using QTimer
   - "Last updated: HH:MM:SS" label bottom-right

PART B — Trend panel (src/gui/trend_panel.py):
1. `TrendPanel(QWidget)`:
   - Two tabs: "Today by Hour" and "Last 7 Days"
   - Both tabs use PyQtGraph PlotWidget for line charts
   - Three lines per chart: one per violation type
     - Repeated Failed Logins: purple line
     - Unauthorized Access: red line
     - Off-Hours Logins: amber line
   - X-axis: hours (0–23) for today tab, dates for 7-day tab
   - Y-axis: violation count
   - Legend visible
   - Chart background matches application background colour

PART C — Source host filter (integration with R3):
1. Add source host dropdown to the overview panel (mirrors violations table filter)
2. All counts and charts update when host filter changes
3. "All Hosts" shows aggregate across all machines

**Acceptance Criteria:**
- [ ] Overview panel shows correct total violation count from database
- [ ] Critical, High, Medium+Low counts match database values
- [ ] Breakdown bars reflect correct proportions for each violation type
- [ ] Doughnut chart segments are correctly proportioned and colour-coded
- [ ] Trend chart shows correct data for today by hour
- [ ] Trend chart shows correct data for last 7 days
- [ ] Auto-refresh updates counts every 30 seconds without user action
- [ ] Host filter on overview panel works correctly
- [ ] All 121 original tests still pass

**Files created in this phase:**
- `src/gui/overview_panel.py`
- `src/gui/trend_panel.py`

**Files modified in this phase:**
- `src/gui/main_window.py` — register new panels in QStackedWidget
- `src/gui/data_access.py` — add trend query functions
- `REWORK_PROGRESS.md`

---

## Phase R5 — Violation Detail View and Live Feed

**Goal:** Build the detail panel that opens when a violation row is clicked, and the
live feed panel that shows new violations in real time without requiring a refresh.

**Dependency:** Phase R3 and R4 must be complete.

**What Claude Code must do:**

PART A — Detail panel (src/gui/detail_panel.py):
1. `DetailPanel(QWidget)`:
   - Opens when a violation row is clicked in the violations table
   - Shows as a right-side slide-in panel OR a modal dialog (choose modal for simplicity)
   - Content:
     - Severity badge (large, colour-coded)
     - Risk score: "Score: 20 / 25"
     - Score breakdown: "Likelihood: 4 × Impact: 5 = 20"
     - Violation type with plain English description
     - Source host
     - Timestamp
     - Log excerpt (the raw log line that triggered the violation)
     - Recommended action (full text, not truncated)
       - Low: "Log and monitor. No immediate action required."
       - Medium: "Review at next available opportunity."
       - High: "Investigate promptly. Consider temporary account lock."
       - Critical: "Immediate investigation and escalation required."
   - Close button top-right
   - "Export this violation" button — copies formatted summary to clipboard

PART B — Live feed panel (src/gui/live_feed.py):
1. `LiveFeedPanel(QWidget)`:
   - Shows new violations as they are detected, newest at top
   - Each entry is a compact card: severity badge | type | host | time
   - Uses QTimer polling the database every 3 seconds for new violations
     (stores last_seen_id, only fetches rows with id > last_seen_id)
   - New entries animate in (fade or slide, keep it subtle)
   - Maximum 100 entries visible; older entries drop off the bottom
   - "Clear" button resets the feed display (does not delete from database)
   - "Pause" toggle stops new entries appearing (useful during review)

PART C — Wire detail panel into violations table:
1. Clicking a row in `ViolationsTable` opens `DetailPanel` with that violation's data
2. Pass violation_id to `DetailPanel`; panel fetches full detail from database

**Acceptance Criteria:**
- [ ] Clicking a violation row opens the detail panel with correct data
- [ ] Score breakdown shows correct likelihood, impact, and product
- [ ] Recommended action text matches severity tier exactly (per IR Table 3.3)
- [ ] Log excerpt shown in detail panel matches the raw line in the database
- [ ] Live feed shows new violations within 5 seconds of detection
- [ ] Live feed does not duplicate entries on refresh
- [ ] Pause button stops new entries appearing; unpause resumes
- [ ] Export button copies formatted violation summary to clipboard
- [ ] All 121 original tests still pass

**Files created in this phase:**
- `src/gui/detail_panel.py`
- `src/gui/live_feed.py`

**Files modified in this phase:**
- `src/gui/violations_table.py` — wire row click to detail panel
- `src/gui/main_window.py` — register live feed panel
- `src/gui/data_access.py` — add get_new_violations_since(id) query
- `REWORK_PROGRESS.md`

---

## Phase R6 — Setup Wizard

**Goal:** Build the 3-screen guided setup wizard that runs on first launch. After the
wizard completes, the user is taken directly into the main window. On all subsequent
launches, the wizard is skipped.

**Dependency:** All of R3, R4, R5 must be complete. The wizard launches into a
complete system. Building it before the system is complete means the wizard's
"launch into app" step has nothing to land on.

**What Claude Code must do:**

PART A — Wizard (src/gui/wizard.py):
1. `SetupWizard(QWizard)`:
   - Uses Qt's built-in QWizard component for step progression
   - 3 pages, back/next/finish navigation built in

   PAGE 1 — Mode Selection:
   - Title: "Welcome to CyberMon"
   - Subtitle: "How would you like to use CyberMon?"
   - Two large buttons with icons and descriptions:
     - "Just this computer"
       Sub-text: "Monitor log files on this machine only. No network setup needed."
     - "Monitor multiple computers"
       Sub-text: "Set up a central monitoring server. Other machines send logs here."
   - Buttons are mutually exclusive (selecting one deselects the other)
   - Cannot proceed until one is selected

   PAGE 2a — Standalone Configuration:
   - Shown only if "Just this computer" was selected on Page 1
   - Title: "Where are your log files?"
   - Two file path fields with Browse buttons:
     - Auth log path (default: logs/auth.log)
     - Web access log path (default: logs/access.log)
   - "Test paths" button — checks if files exist and shows green tick or red X
   - Business hours configuration:
     - Start time (default: 08:00)
     - End time (default: 18:00)
     - Days: Mon–Fri checkboxes (all checked by default)
   - Brute force threshold: number input (default: 5 attempts)
   - Brute force window: number input in minutes (default: 10)

   PAGE 2b — Network Configuration:
   - Shown only if "Monitor multiple computers" was selected on Page 1
   - Title: "Set up your monitoring server"
   - Auto-detected IP shown: "This machine's IP address: 192.168.x.x"
   - Confirm or override IP field
   - Port field (default: 5001)
   - Info box: "Install CyberMonAgent.exe on each computer you want to monitor.
     Enter this server's IP address when the agent asks."
   - Same business hours and threshold fields as Page 2a

   PAGE 3 — Confirmation:
   - Title: "You're all set"
   - Summary of chosen settings (mode, paths, thresholds)
   - "Start Monitoring" button (Finish button)
   - On finish: write all settings to config.yaml, launch MainWindow

2. First-run detection in main.py:
   - Check if `config.yaml` has a `setup_complete: true` key
   - If not: show SetupWizard, then MainWindow
   - If yes: show MainWindow directly
   - Wizard sets `setup_complete: true` in config.yaml on completion

PART B — Settings panel (src/gui/settings_panel.py):
1. `SettingsPanel(QWidget)`:
   - Available from sidebar "Settings" item at any time
   - Shows same fields as wizard Page 2 (mode-appropriate)
   - "Save" button writes changes to config.yaml
   - "Re-run Setup Wizard" button resets setup_complete and restarts the wizard
   - Changes to thresholds take effect on next pipeline run

PART C — Tests:
1. Create `tests/test_wizard.py`:
   - Test that wizard writes correct config.yaml for standalone mode
   - Test that wizard writes correct config.yaml for network mode
   - Test that first-run detection shows wizard when setup_complete is missing
   - Test that first-run detection skips wizard when setup_complete is true

**Acceptance Criteria:**
- [ ] First launch (no config.yaml) shows wizard before main window
- [ ] Selecting standalone mode shows Page 2a (file paths)
- [ ] Selecting network mode shows Page 2b (server IP)
- [ ] "Test paths" button correctly identifies missing files
- [ ] Wizard writes correct values to config.yaml on completion
- [ ] setup_complete: true is written to config.yaml on completion
- [ ] Second launch skips wizard and goes directly to main window
- [ ] Settings panel shows current config values
- [ ] Saving from settings panel updates config.yaml correctly
- [ ] "Re-run wizard" resets setup_complete and shows wizard on next launch
- [ ] All wizard tests pass
- [ ] All 121 original tests still pass

**Files created in this phase:**
- `src/gui/wizard.py`
- `src/gui/settings_panel.py`
- `tests/test_wizard.py`

**Files modified in this phase:**
- `main.py` — first-run detection logic
- `config/config.yaml` — add setup_complete key
- `src/gui/main_window.py` — add Settings to sidebar
- `REWORK_PROGRESS.md`

---

## Phase R7 — Export, Error Handling, Empty States, and Polish

**Goal:** Make the application production-ready for a non-technical user. Handle
every edge case gracefully. Remove the old Flask dashboard files. Ensure all four
severity tiers appear in demo data.

**Dependency:** R6 must be complete.

**What Claude Code must do:**

PART A — CSV export:
1. Add "Export CSV" button to the violations table panel
2. Opens a file save dialog (QFileDialog)
3. Exports all currently visible violations (respecting host filter) to CSV
4. CSV columns: timestamp, violation_type, source_host, likelihood, impact,
   risk_score, severity, recommended_action, log_excerpt

PART B — Error handling:
1. Log file not found on startup:
   - Show a non-blocking warning banner at the top of the main window
   - "Log file not found at [path]. Check your settings."
   - Link to Settings panel
2. Database empty (no violations yet):
   - Show friendly empty state in violations table:
     "No violations detected yet. CyberMon is monitoring your logs."
   - Show in overview panel: all counts show 0, chart is empty but labelled
3. Agent connection failure (network mode):
   - Show connection status indicator in sidebar (green dot / red dot)
   - Red dot + tooltip: "No agents connected. Check agent configuration."
4. Pipeline error:
   - Catch all unhandled exceptions in pipeline
   - Log to `cybermon.log`
   - Show error notification in the app (not a crash dialog)

PART C — Demo data fix:
1. Update `simulate.py` to generate violations across all four severity tiers:
   - Add Critical: sustained brute force on admin account (Likelihood 5, Impact 5)
   - Add Low: single failed login on low-privilege account (Likelihood 1, Impact 1)
   - Existing Medium and High patterns kept as-is
2. Confirm all four tiers visible in violations table after running simulate.py

PART D — Remove old Flask dashboard:
1. Delete or archive `src/dashboard/` (old Flask routes and templates)
2. Keep `server/ingest_endpoint.py` — still needed for network mode
3. Remove Flask route imports from `main.py` that are no longer used
4. Confirm `python main.py` still runs cleanly after removal

PART E — Final test pass:
1. Run full test suite
2. Target: 140+ tests passing (121 original + new tests from R2, R6, R7)
3. Fix any failing tests

**Acceptance Criteria:**
- [ ] CSV export produces a correctly formatted file with all expected columns
- [ ] File save dialog appears and respects the chosen file path
- [ ] Missing log file shows warning banner (not a crash)
- [ ] Empty database shows friendly empty state in all panels
- [ ] simulate.py produces violations in all four severity tiers
- [ ] All four severity tiers visible in violations table with correct colours
- [ ] Old Flask dashboard files removed, app still starts cleanly
- [ ] 140+ tests passing
- [ ] No unhandled exceptions under normal operation

**Files created in this phase:**
- None (changes are to existing files)

**Files modified in this phase:**
- `src/gui/violations_table.py` — CSV export
- `src/gui/overview_panel.py` — empty state
- `src/gui/live_feed.py` — connection status
- `simulate.py` — all four severity tiers
- `main.py` — remove old dashboard routes
- `REWORK_PROGRESS.md`

**Files deleted in this phase:**
- `src/dashboard/` (entire folder)
- Old Flask HTML templates (if separate from ingest_endpoint)

---

## Phase R8 — User Acceptance Testing

**Goal:** Validate that a non-technical user can complete core tasks unsupervised
in both standalone and network modes. Fix all usability failures before packaging.

**Dependency:** R7 must be complete. No code changes after R8 except for UAT fixes.

**This phase is executed by you (Mak), not Claude Code.**

**UAT Protocol:**

PARTICIPANT CRITERIA:
- At least 2 participants for standalone mode
- At least 1 participant for network mode (can be a classmate with a second laptop)
- Participants must not have seen the application before
- Participants should not be studying computer science (test non-technical users)

TASK LIST (give to participant, no verbal guidance):
1. Install and launch the application for the first time
2. Choose standalone mode and configure it to watch the default log files
3. Navigate to the violations list and find the highest severity violation
4. Open that violation's detail view and read the recommended action
5. Filter the violations list to show only one specific machine
6. Export the violations list to a CSV file
7. Navigate to the trend chart and identify which day had the most violations
8. Go to Settings and change the brute force threshold to 3

OBSERVATION LOG (fill in for each participant):
- Task 1–8: Complete / Incomplete / Could not start
- Points of confusion (quote what they said or did)
- Time to complete all tasks (minutes)

PASS CRITERIA (overall):
- [ ] Both standalone participants complete all 8 tasks without asking for help
- [ ] Network participant completes tasks 1–7 without asking for help
- [ ] No participant is confused by the same UI element twice
- [ ] Average time to complete all tasks is under 15 minutes

**After UAT — Claude Code fixes:**
1. For every point of confusion noted in the observation log:
   - Describe the confusion to Claude Code
   - CC proposes a fix
   - You approve and CC implements
2. Re-run test suite after fixes — all tests must still pass

**Files modified in this phase:**
- Whichever GUI files require usability fixes (determined by UAT results)
- `REWORK_PROGRESS.md` — UAT results and fixes recorded

---

## Phase R9 — PyInstaller Packaging

**Goal:** Package the application into two distributable .exe files that run on
a clean Windows machine with no Python, no pip, and no command line required.

**Dependency:** R8 must be complete and all UAT fixes applied.

**What Claude Code must do:**

PART A — CyberMon.exe (main application):
1. Create `build/cybermon.spec` PyInstaller spec file:
   - Entry point: `main.py`
   - Name: `CyberMon`
   - Windowed mode (no console window)
   - Include: `config/`, `logs/` (empty placeholder), `src/`
   - Include PyQt6 and PyQtGraph binaries
   - Icon: `assets/icon.ico` (create a simple shield icon if not exists)
2. Add path helper to `main.py`:
   - Use `sys._MEIPASS` for resource paths when running as bundled exe
   - All file path references in the app must use this helper
3. Build command: `pyinstaller build/cybermon.spec`
4. Test the built exe on the development machine

PART B — CyberMonAgent.exe:
1. Create `build/agent.spec` PyInstaller spec file:
   - Entry point: `agent_main.py`
   - Name: `CyberMonAgent`
   - Windowed mode
   - Include: `agent_config.yaml` (default config)
2. Build command: `pyinstaller build/agent.spec`
3. Test the built agent exe on the development machine

PART C — Distribution package:
1. Create `dist/CyberMon_v2.0.zip` containing:
   - `CyberMon.exe`
   - `CyberMonAgent.exe`
   - `README.txt` (3 sentences: what it is, double-click to start, agent instructions)
2. Document exact build commands in `REWORK_PROGRESS.md`

PART D — Clean machine test (you run this, not CC):
- Copy the zip to a machine with no Python installed (or a fresh VM)
- Unzip and double-click `CyberMon.exe`
- Confirm: wizard appears, app loads, violations show after simulate.py run
- Confirm: no "Python not found" or DLL errors

**Acceptance Criteria:**
- [ ] `CyberMon.exe` launches without any Python installation present
- [ ] `CyberMon.exe` shows setup wizard on first launch
- [ ] `CyberMon.exe` shows main dashboard after wizard completion
- [ ] `CyberMonAgent.exe` launches and tails a log file without Python
- [ ] Both exes under 150MB each
- [ ] No console window appears to the user
- [ ] Clean machine test passes with no errors

**Files created in this phase:**
- `build/cybermon.spec`
- `build/agent.spec`
- `assets/icon.ico`
- `dist/CyberMon_v2.0.zip`

**Files modified in this phase:**
- `main.py` — path helper for bundled resources
- `agent_main.py` — path helper for bundled resources
- `REWORK_PROGRESS.md`

---

## Phase R10 — IR Update and GitHub Polish

**Goal:** Update the IR to document the rework architecture and produce a clean,
professional GitHub repository that serves as a portfolio piece.

**Dependency:** R9 must be complete.

**This phase is primarily executed by you (Mak), not Claude Code.**

**What you must do:**
1. Update IR Chapter 3 (Section 3.4 Proposed System Architecture):
   - Update Figure 3.3 to show dual-mode pipeline with agent
   - Update Table 3.4 to include agent component and PyQt6 GUI
   - Add a paragraph describing dual-mode deployment
2. Update IR Chapter 4 (Conclusion):
   - Section 4.1: Update achievements to include rework deliverables
   - Section 4.2: Strengthen SDG 9 argument — dual-mode makes the tool
     accessible to more organisations, including multi-machine setups
3. Note NFR-05 limitation update:
   - The rework fixes the database-clearing-on-each-run limitation
   - Update NFR-05 status in IR from "known limitation" to "resolved"

**What Claude Code does:**
1. Write a clean `README.md` for the GitHub repo:
   - Project title and one-sentence description
   - Architecture diagram (text-based or linked image)
   - Two sections: Standalone Mode and Network Mode, each with setup steps
   - Screenshots placeholder (you fill in)
   - Requirements: Windows, no Python needed for .exe users
   - For developers: `pip install -r requirements.txt` then `python main.py`
   - License: MIT
2. Create `CHANGELOG.md`:
   - v1.0: original Flask build (Phases 0–6)
   - v2.0: PyQt6 desktop rework (Phases R0–R9), dual-mode, agent, wizard

**Acceptance Criteria:**
- [ ] IR Chapter 3 architecture section reflects dual-mode system
- [ ] IR Chapter 4 updated achievements include rework
- [ ] NFR-05 status updated in IR
- [ ] README.md is clear enough for a non-developer to understand what the project does
- [ ] README.md setup instructions are correct and complete
- [ ] CHANGELOG.md documents both versions

---

## Summary Table

| Phase | Key Deliverable | Depends On | Complexity |
|-------|----------------|------------|------------|
| R0 | Real log validation, parser fixes | Nothing | Low |
| R1 | source_host in all three tables | R0 | Low-Medium |
| R2 | agent.py + /ingest endpoint | R1 | Medium |
| R3 | PyQt6 main window + violations table | R1 | High |
| R4 | Overview panel + trend charts | R3 | Medium-High |
| R5 | Detail panel + live feed | R3, R4 | Medium |
| R6 | 3-screen setup wizard | R3, R4, R5 | Medium |
| R7 | Export, error handling, empty states, polish | R6 | Medium |
| R8 | UAT — both modes, non-technical users | R7 | N/A (you) |
| R9 | PyInstaller packaging — two exes | R8 | Medium |
| R10 | IR update + GitHub README | R9 | Low (you) |

---

## Rules for Claude Code When Using This File

1. Read this entire file before starting any phase
2. Complete all acceptance criteria for a phase before moving to the next
3. Never modify files listed under "must NOT change" for a phase
4. After each phase, update REWORK_PROGRESS.md with results
5. If a phase acceptance criterion cannot be met, stop and report why — do not
   proceed to the next phase with a failing criterion
6. All 121 original tests must pass at the end of every phase
7. Do not invent features. If something is not described in a phase, do not build it.
8. When in doubt, do less and ask. Overbuilding is harder to undo than underbuilding.
