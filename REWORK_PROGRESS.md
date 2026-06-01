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

**Commit hash:** (pending)

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

**Decision made:** Accept option 1 — proceed to R1 with this criterion documented as an acknowledged deviation. When config.yaml is extended in R2 for agent/server keys, also add /var/www/html to restricted_resources so real-log runs will produce unauthorized_access violations going forward. The off_hours_login gap is accepted: the existing unit tests (logs/samples/auth.log) confirm the rule fires correctly; the real-log gap is a year-metadata limitation inherent to the syslog format.

**Reason:** The parser is correct. The detection rules are correct. The gap is a data/config mismatch specific to these log files. Blocking R1 for this would delay the rework for a problem that has no parser-level solution.

**Impact on REWORK_PHASES.md:** None — the real-log validation goal (confirm parser handles real data) is met. The violation-coverage sub-criterion is documented as a known deviation, not a silent skip.

---

### Phase R1 — Schema Update and Source Host Tagging
**Status:** Not started
**Date Started:**
**Date Completed:**

**Acceptance Criteria Results:**
- [ ] events table has source_host column
- [ ] violations table has source_host column
- [ ] risk_scores table has source_host column
- [ ] All INSERTs write non-null source_host
- [ ] All SELECTs return source_host
- [ ] migrate_db.py runs without error
- [ ] All 121 original tests passing
- [ ] python main.py runs end-to-end in standalone mode

**What was built:**

**What didn't work and how it was fixed:**

**Deviations from REWORK_PHASES.md (if any):**

**Test count at end of phase:**

**Commit hash:**

---

### Phase R2 — Agent and Ingest Endpoint
**Status:** Not started
**Date Started:**
**Date Completed:**

**Acceptance Criteria Results:**
- [ ] Agent tails file and POSTs new lines locally
- [ ] Ingest endpoint receives POST and runs pipeline
- [ ] Violations from agent POST have correct source_host in database
- [ ] Ingest endpoint returns HTTP 400 on malformed body
- [ ] Agent retries 3 times on connection failure
- [ ] All new tests passing
- [ ] All 121 original tests passing
- [ ] mode: standalone leaves original behaviour unchanged

**Simulated network test result:**

**What was built:**

**What didn't work and how it was fixed:**

**Deviations from REWORK_PHASES.md (if any):**

**Test count at end of phase:**

**Commit hash:**

---

### Phase R3 — PyQt6 Main Window and Violations Table
**Status:** Not started
**Date Started:**
**Date Completed:**

**Acceptance Criteria Results:**
- [ ] python main.py launches native desktop window (no browser)
- [ ] Sidebar navigation switches panels without error
- [ ] Violations table shows all violations from database
- [ ] Violations sorted by risk score descending
- [ ] Severity badges colour-coded for all four tiers
- [ ] Host filter dropdown shows unique source_host values
- [ ] Host filter updates table correctly
- [ ] Refresh button re-queries and updates
- [ ] Row click does not crash
- [ ] All 121 original tests passing
- [ ] Window usable at 1200x750

**What was built:**

**What didn't work and how it was fixed:**

**Deviations from REWORK_PHASES.md (if any):**

**Test count at end of phase:**

**Commit hash:**

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
