# R11_HARDENING_AND_EVALUATION.md
# CyberMon — Hardening and Evaluation Phase
# Static reference document. Created once. Follow the same rules as REWORK_PHASES.md.
# Add to repo root alongside REWORK_PROGRESS.md before starting any R11 part.

---

## What This Phase Is

R11 closes the gap between what the project *claims* and what the code *does*.
It is structured as four sequential parts (R11-A through R11-D), each independently
committable, each with its own acceptance criteria. Parts must be completed in order.

R11-A: API security on the ingest endpoint (kill-shot fix)
R11-B: Stateful failed-login detection in network mode (differentiator fix)
R11-C: Config-driven scoring (makes the central gap-analysis claim true)
R11-D: Alert deduplication and detection accuracy improvements

A fifth part (R11-E) covers evaluation artifacts — synthetic log labelling,
performance benchmarking, and the simulate.py tier-coverage fix. R11-E requires
no code changes to the pipeline; it produces data and a report table only.

---

## What Does NOT Change in R11 (unless explicitly stated per part)

- `src/ingestion/` — UNCHANGED
- `src/detection/rules/off_hours.py` — UNCHANGED (except R11-D item 3)
- `src/detection/rules/unauthorized_access.py` — UNCHANGED (except R11-D items 4–5)
- `src/storage/db.py` — UNCHANGED
- `src/storage/writer.py` — UNCHANGED
- `src/gui/` — UNCHANGED (UI changes come from UAT in R8 only)
- `REWORK_PHASES.md` — NEVER edited
- All existing tests must pass after every part

---

## Rules for Claude Code When Using This File

1. Read this ENTIRE file before starting any part
2. Complete ALL acceptance criteria for a part before moving to the next
3. After each part, commit with the exact message format shown at the end of that part
4. Update REWORK_PROGRESS.md after every part — mark status, record test count, record commit hash
5. If an acceptance criterion cannot be met, STOP and report why — do not proceed
6. All 142 existing tests must pass at the end of every part
7. Do not build anything not described in a part
8. When in doubt, do less and report back

---

## Part R11-A — Ingest Endpoint Authentication and Rate Protection

### Why this exists

`server/ingest_endpoint.py` currently accepts POST /ingest from any caller with no
authentication. An attacker on the same LAN can:
  - Forge violations (poison the dashboard with false data)
  - Flood the SQLite database until disk is full (denial of service)
  - Spam Low-severity noise to bury real activity

This is the first question any security-literate examiner or interviewer will ask
about a system that calls itself a security monitoring tool. It must be fixed before
any demo or submission.

The threat model is explicitly a trusted LAN (TLS is not required and is documented
as future work), but authentication IS required.

### What Claude Code must implement

**PART A1 — Shared secret in config**

In `config/config.yaml` and `config/config_default.yaml`, add under `server:`:

```yaml
server:
  host: 0.0.0.0
  port: 5001
  api_key: "CHANGE_ME_BEFORE_DEPLOY"   # shared secret for agent→server auth
```

The string `CHANGE_ME_BEFORE_DEPLOY` is the default. It is intentionally weak so
users know to change it. Do NOT generate a random UUID as the default — that would
make config files non-reproducible in tests.

In `agent_config.yaml` (the agent's default config), add:

```yaml
api_key: "CHANGE_ME_BEFORE_DEPLOY"
```

This value must match the server's `server.api_key` for the agent to be accepted.

**PART A2 — Server-side enforcement in ingest_endpoint.py**

Modify `server/ingest_endpoint.py` to:

1. Read `server.api_key` from config at startup (load once into a module-level
   variable, not on every request — config load on every request is too slow):

```python
_config = _load_config()
_EXPECTED_KEY = _config.get("server", {}).get("api_key", "")
```

2. On every POST /ingest, check the `X-API-Key` header BEFORE processing any body:

```python
received_key = request.headers.get("X-API-Key", "")
if not received_key or received_key != _EXPECTED_KEY:
    return jsonify({"error": "unauthorized"}), 401
```

3. Add a request body size cap. Reject any request whose Content-Length exceeds
   2MB or whose `lines` list contains more than 5000 items:

```python
if request.content_length and request.content_length > 2 * 1024 * 1024:
    return jsonify({"error": "payload too large"}), 413

# ... after JSON parsing:
if len(body.get("lines", [])) > 5000:
    return jsonify({"error": "batch too large — max 5000 lines per request"}), 413
```

4. The `host` field from the POST body must be sanitised. Limit it to 64 characters,
   alphanumeric plus hyphens, underscores, and dots only. Reject anything that does
   not match:

```python
import re
_HOST_RE = re.compile(r'^[\w\.\-]{1,64}$')

if not _HOST_RE.match(host):
    return jsonify({"error": "invalid host identifier"}), 400
```

**PART A3 — Agent sends the API key on every POST**

Modify `src/agent/agent.py` to:

1. Accept `api_key: str` as a constructor parameter (default `""`).
2. Include the key as a header on every POST request:

```python
headers = {"X-API-Key": self.api_key, "Content-Type": "application/json"}
resp = requests.post(self.url, json=payload, headers=headers, timeout=5)
```

3. The constructor signature becomes:

```python
def __init__(
    self,
    server_ip: str,
    server_port: int,
    log_path: str,
    host_id: str,
    api_key: str = "",
    retry_attempts: int = 3,
    retry_delay_seconds: int = 2,
) -> None:
```

**PART A4 — agent_main.py reads api_key from agent_config.yaml**

Modify `agent_main.py` to pass `api_key` from config to the `CyberMonAgent`
constructor. If the key is missing from config, use `""` as default and print
a warning:

```
[CyberMonAgent] WARNING: no api_key configured — server will reject requests.
Edit agent_config.yaml and set api_key to match the server's api_key.
```

**PART A5 — Tests for R11-A**

Create `tests/test_r11a_auth.py`. It must contain ALL of the following test functions.
Do not skip any. Each test must be independently runnable with pytest.

```
test_missing_api_key_returns_401
test_wrong_api_key_returns_401
test_correct_api_key_accepted
test_empty_string_key_returns_401
test_payload_too_large_returns_413
test_batch_over_5000_lines_returns_413
test_invalid_host_chars_returns_400
test_host_too_long_returns_400
test_agent_sends_api_key_header
test_agent_missing_key_sends_empty_header
```

For the endpoint tests, use Flask's test client (same pattern as
`tests/test_ingest_endpoint.py`) but set the `EXPECTED_KEY` via the module-level
variable override rather than patching config — import `ingest_app` and use
`with ingest_app.test_client() as client`.

For agent tests, use `unittest.mock.patch('requests.post')` (same pattern as
`tests/test_agent.py`) and assert that `call_args.kwargs['headers']` (or
`call_args[1]['headers']`) contains the correct `X-API-Key` value.

**PART A6 — Documentation**

In `RUNNING.md`, add a section titled "Network Mode Security" that states:

1. The ingest endpoint uses a shared API key for authentication
2. How to change the key (edit `server.api_key` in config.yaml on the server,
   edit `api_key` in agent_config.yaml on each agent machine — they must match)
3. A stated limitation: traffic is plaintext HTTP; on untrusted networks, run
   the agent and server on a VPN or dedicated management VLAN
4. The host identifier sent by agents is validated but trusted — a compromised
   agent machine can still misreport its host_id; this is a known limitation

### Acceptance Criteria — R11-A

- [ ] POST /ingest without X-API-Key header returns HTTP 401
- [ ] POST /ingest with wrong key returns HTTP 401
- [ ] POST /ingest with correct key proceeds normally (HTTP 200)
- [ ] POST body > 2MB returns HTTP 413
- [ ] POST with lines list > 5000 items returns HTTP 413
- [ ] POST with host containing invalid characters returns HTTP 400
- [ ] POST with host longer than 64 chars returns HTTP 400
- [ ] CyberMonAgent sends X-API-Key header on every POST (tested with mock)
- [ ] agent_main.py reads api_key from agent_config.yaml
- [ ] All 10 tests in test_r11a_auth.py pass
- [ ] All 142 existing tests still pass
- [ ] RUNNING.md network security section added
- [ ] config.yaml and config_default.yaml both contain server.api_key field

**Commit message:** `R11-A: ingest endpoint auth — API key header, payload limits, host validation`

---

## Part R11-B — Stateful Failed-Login Detection in Network Mode

### Why this exists

`server/ingest_endpoint.py` calls `run_detection(events_of_this_batch, config)`.
The agent drains its buffer and POSTs every ~0.5 seconds. An attacker making one
failed SSH attempt per second sends 1–2 events per batch. The threshold
(`detection.failed_logins.threshold`, default 2) is never crossed within any single
batch. The violation is NEVER detected in network mode.

Your standalone LogWatcher got this right — it keeps a stateful per-user deque across
lines. The network path has weaker detection than the mode you were trying to outgrow.
This must be fixed.

The correct fix is to run failed-login detection by querying recent events from the
SQLite database for each arriving batch, rather than looking only at the current batch.
This leverages the storage layer (which already exists) and requires no new tables.

### What Claude Code must implement

**PART B1 — New function in src/detection/rules/failed_logins.py**

Add a second public function alongside the existing `detect_failed_logins`:

```python
def detect_failed_logins_from_db(
    events: list[dict],
    config: dict,
    db_path: str,
    source_host: str,
) -> list[dict]:
    """
    Stateful failed-login detection for network mode.

    Instead of scanning only the current batch, this function:
    1. Identifies unique (source_host, username) pairs in the incoming events
    2. Queries the database for ALL failed-login events for those pairs
       within the configured time window
    3. Runs the threshold check against the combined DB + batch count
    4. Returns violations only for pairs that cross the threshold

    This ensures that a slow brute force spread across many small batches
    is detected correctly — the batch-only approach misses it entirely.
    """
```

Implementation requirements:

1. Import `sqlite3` and `datetime`. Do NOT import from `src.storage` (avoid circular
   imports — use raw sqlite3 calls here, as this is a detection rule).

2. For each unique `(username, source_host)` pair in the `events` list where
   `status_code == "FAILED"`:
   - Query the `events` table for rows matching that pair within the time window:
     ```sql
     SELECT timestamp FROM events
     WHERE username = ?
       AND source_host = ?
       AND status_code = 'FAILED'
       AND timestamp >= ?
     ORDER BY timestamp ASC
     ```
   - The `timestamp >= ?` bound is `(now - timedelta(minutes=window_minutes)).isoformat()`
   - Count the results. If count > threshold, emit a violation.
   - The violation dict format is identical to `detect_failed_logins` output.

3. Deduplicate: if the same (username, source_host) pair already has an open
   violation in the database within the last `window_minutes`, do NOT emit a new one.
   Check for this with:
   ```sql
   SELECT COUNT(*) FROM violations
   WHERE violation_type = 'failed_logins'
     AND username = ?
     AND source_host = ?
     AND timestamp >= ?
   ```
   If count > 0, skip — the violation is already recorded for this window.

4. Return a list of violation dicts (may be empty).

**PART B2 — Wire it into server/ingest_endpoint.py**

In `server/ingest_endpoint.py`, replace the call to `run_detection` for failed logins
with the new stateful function. Specifically:

1. Import `detect_failed_logins_from_db` from `src.detection.rules.failed_logins`
2. Split detection into two phases:
   - Non-stateful detections (unauthorized_access, off_hours): still use `run_detection`
     (batch-only is fine for these — each event is self-contained)
   - Stateful detection (failed_logins): use `detect_failed_logins_from_db`
3. Merge results and pass to `score_all_violations` as before

The updated detection block in `ingest_endpoint.py` should look like:

```python
from src.detection.rules.failed_logins import detect_failed_logins_from_db
from src.detection.rules.unauthorized_access import detect_unauthorized_access
from src.detection.rules.off_hours import detect_off_hours_logins

# Stateful: query DB for full window context
failed_login_violations = detect_failed_logins_from_db(
    events, config, db_path, host
)

# Stateless: each event is self-contained
unauth_violations = detect_unauthorized_access(events, config)
off_hours_violations = detect_off_hours_logins(events, config)

violations = failed_login_violations + unauth_violations + off_hours_violations
```

NOTE: Do NOT change the standalone path (`main.py` and `src/ingestion/watcher.py`).
The LogWatcher's in-memory deque approach remains correct for standalone mode.

**PART B3 — Tests for R11-B**

Create `tests/test_r11b_stateful_detection.py`. It must contain ALL of the following:

```
test_single_event_below_threshold_no_violation
    — one FAILED event in DB, one arrives in batch; threshold=2; no violation

test_db_plus_batch_crosses_threshold
    — threshold=2; one FAILED event already in DB within window;
      one arrives in batch; violation IS detected

test_spread_across_three_batches
    — threshold=3; two FAILED events in DB; one arrives in batch;
      violation IS detected (this is the slow brute-force scenario)

test_old_db_event_outside_window_ignored
    — one FAILED event in DB but older than window_minutes; one in batch;
      total = 1 (DB event excluded); threshold=2; no violation

test_dedup_suppresses_second_violation_same_window
    — violation already exists in violations table for this user/host/window;
      even though threshold crossed, no new violation emitted

test_different_usernames_not_mixed
    — user A has 3 failures, user B has 1; only user A gets a violation

test_different_source_hosts_not_mixed
    — same username, different source_host values; counted separately
```

Each test must create a temporary SQLite database (use `tmp_path` pytest fixture),
seed it using `src.storage.db.init_db` and `src.storage.writer.insert_events`,
then call `detect_failed_logins_from_db` directly and assert the output.

**PART B4 — Integration test update**

In `tests/test_ingest_endpoint.py`, add ONE test:

```
test_slow_brute_force_detected_across_batches
    — POST batch of 1 failed login; POST second batch of 1 failed login (same user,
      same host); assert that after the second POST the response contains
      violations_detected >= 1
```

This requires the test to use a real (temp) database, not mocked storage.
Follow the pattern used in `tests/test_integration.py` for DB setup.

### Acceptance Criteria — R11-B

- [ ] `detect_failed_logins_from_db` exists in `src/detection/rules/failed_logins.py`
- [ ] Slow brute force (one event per batch, threshold=2) is detected after second batch
- [ ] Events outside the time window are excluded from the count
- [ ] Duplicate violations within the same window are suppressed
- [ ] Different usernames and different source_hosts are counted independently
- [ ] Standalone path (LogWatcher + main.py) is UNCHANGED — no regression
- [ ] All 7 tests in test_r11b_stateful_detection.py pass
- [ ] Integration test for slow brute force passes
- [ ] All 142 existing tests still pass
- [ ] test_r11b passes with both threshold=2 and threshold=5 configs

**Commit message:** `R11-B: stateful failed-login detection in network mode via DB query`

---

## Part R11-C — Config-Driven Scoring (Making the Differentiator Real)

### Why this exists

IR Table 2.6 lists "Configurable risk scoring: Yes, core feature" as the key gap
between the proposed system and Wazuh. But `src/scoring/rules.py` has hardcoded:

```python
_HIGH_IMPACT_RESOURCES = {"/admin", "/.env", "/phpmyadmin"}
_MED_IMPACT_RESOURCES  = {"/config", "/wp-admin"}
_HIGH_IMPACT_USERS     = {"root", "admin"}
```

And hardcoded likelihood bands:
```python
if count <= 5:  return 2
if count <= 9:  return 3
if count <= 19: return 4
return 5
```

An organisation whose admin account is named `superuser` instead of `admin` gets
Impact 2 instead of 4, and cannot change it without editing source code — exactly
the Wazuh-style "edit the internals" problem cited in the IR as a weakness.

This part moves all those constants into `config.yaml` and reads them at scoring time.
The Settings panel in the GUI exposes them as editable fields for the user.

### What Claude Code must implement

**PART C1 — Extend config.yaml and config_default.yaml**

Add a `scoring.rules` section to BOTH files. The existing `scoring.severity_tiers`
section must remain UNCHANGED. Add AFTER it:

```yaml
scoring:
  severity_tiers:           # existing — do not touch
    low:      { min: 1,  max: 4  }
    medium:   { min: 5,  max: 9  }
    high:     { min: 10, max: 16 }
    critical: { min: 17, max: 25 }

  rules:                    # NEW — moved from hardcoded constants in scorer.py
    high_impact_users:
      - root
      - admin
    high_impact_resources:
      - /admin
      - /.env
      - /phpmyadmin
    med_impact_resources:
      - /config
      - /wp-admin
    failed_login_likelihood_bands:
      # count <= max_count gets this likelihood value
      # evaluated in order; first match wins
      - { max_count: 5,  likelihood: 2 }
      - { max_count: 9,  likelihood: 3 }
      - { max_count: 19, likelihood: 4 }
      - { max_count: 99999, likelihood: 5 }   # catch-all
    unauthorized_access_default_likelihood: 3
    off_hours_default_likelihood: 2
    off_hours_default_impact: 3
    failed_login_high_user_impact: 4
    failed_login_default_impact: 2
    unauthorized_access_high_resource_impact: 5
    unauthorized_access_med_resource_impact: 3
    unauthorized_access_default_impact: 2
```

**PART C2 — Rewrite src/scoring/rules.py to read from config**

Replace the current hardcoded implementation entirely. The new implementation must:

1. Remove ALL module-level constants (`_HIGH_IMPACT_RESOURCES`, `_MED_IMPACT_RESOURCES`,
   `_HIGH_IMPACT_USERS`).

2. The functions `get_likelihood(violation, config)` and `get_impact(violation, config)`
   must now accept `config` as a second argument and read all values from
   `config["scoring"]["rules"]`.

3. Implement graceful fallback: if `scoring.rules` is absent from config (e.g. an
   older config.yaml that has not been updated), use these hardcoded defaults:
   ```python
   _FALLBACK_HIGH_USERS      = {"root", "admin"}
   _FALLBACK_HIGH_RESOURCES  = {"/admin", "/.env", "/phpmyadmin"}
   _FALLBACK_MED_RESOURCES   = {"/config", "/wp-admin"}
   ```
   Print a one-time warning to stderr:
   `"[CyberMon] WARNING: scoring.rules not found in config — using built-in defaults"`

4. The `_extract_count` helper function must remain (it is used by the likelihood band
   logic). The band evaluation must now read from
   `config["scoring"]["rules"]["failed_login_likelihood_bands"]` if present,
   else fall back to the original hardcoded bands.

5. The signature change propagates to `src/scoring/scorer.py`:
   - `calculate_likelihood(violation, config)` — passes config through to `get_likelihood`
   - `calculate_impact(violation, config)` — passes config through to `get_impact`
   - `score_violation(violation, config)` — already accepts config; update its internal calls

**PART C3 — Update all callers of get_likelihood / get_impact**

Search the entire codebase for calls to `get_likelihood`, `get_impact`,
`calculate_likelihood`, `calculate_impact`. Update every call site to pass `config`.
Files that will need updating:
- `src/scoring/scorer.py`
- Any test file that calls these functions directly

If a test calls these functions without a config argument, pass a minimal config dict:
```python
_MIN_CONFIG = {"scoring": {"severity_tiers": {
    "low": {"min": 1, "max": 4}, "medium": {"min": 5, "max": 9},
    "high": {"min": 10, "max": 16}, "critical": {"min": 17, "max": 25}
}}}
```
Do NOT use a real config file in unit tests — use this minimal dict.

**PART C4 — Settings panel: expose scoring.rules to the user**

In `src/gui/settings_panel.py`, add a new collapsible section titled
"Risk Scoring Rules" between the existing Detection Thresholds section and
the Storage section.

It must contain:
1. A multi-line text field for "High-impact users" (comma-separated, e.g. `root, admin`)
   — reads from and writes to `config["scoring"]["rules"]["high_impact_users"]`
2. A multi-line text field for "High-impact resources" (one per line or comma-separated)
   — reads from and writes to `config["scoring"]["rules"]["high_impact_resources"]`
3. A multi-line text field for "Medium-impact resources"
   — reads from and writes to `config["scoring"]["rules"]["med_impact_resources"]`
4. A "Save" button that writes the updated config back to config.yaml (same mechanism
   used by the existing Save button in settings)
5. A plain-text note below the fields:
   "Changes take effect on the next pipeline run or log file scan."

The GUI is read and updated using the same `_load_config()` / `_save_config()` pattern
already present in `settings_panel.py`. Do NOT introduce a new config-loading mechanism.

**PART C5 — Tests for R11-C**

Create `tests/test_r11c_config_scoring.py`. It must contain ALL of the following:

```
test_custom_high_impact_user_gets_correct_impact
    — config has high_impact_users: ["superuser"]; violation username="superuser";
      assert get_impact returns high_user_impact value

test_default_admin_still_works_with_custom_config
    — config has high_impact_users: ["superuser", "admin"];
      assert admin still gets high impact

test_custom_high_resource_gets_correct_impact
    — config has high_impact_resources: ["/secret"]; violation resource="/secret";
      assert get_impact returns high_resource_impact

test_unconfigured_resource_gets_default_impact
    — violation resource="/someother"; assert get_impact returns default impact

test_likelihood_band_from_config
    — config has a band {max_count: 3, likelihood: 2};
      violation detail="3 failed logins..."; assert get_likelihood returns 2

test_fallback_when_scoring_rules_absent
    — config has NO scoring.rules key; function must not raise; must return
      a valid integer likelihood and impact

test_score_changes_when_config_changes
    — score violation with default config; then score same violation with
      config where high_impact_users includes the username; assert scores differ
```

### Acceptance Criteria — R11-C

- [ ] `src/scoring/rules.py` contains NO hardcoded `_HIGH_IMPACT_RESOURCES`,
      `_MED_IMPACT_RESOURCES`, `_HIGH_IMPACT_USERS` module-level constants
- [ ] `config.yaml` and `config_default.yaml` both contain the `scoring.rules` section
- [ ] Changing `high_impact_users` in config changes the score without code edits
- [ ] Changing `high_impact_resources` in config changes the score without code edits
- [ ] Settings panel has "Risk Scoring Rules" section with three editable fields
- [ ] Saving from settings panel writes back to config.yaml correctly
- [ ] Fallback behaviour works when scoring.rules is absent from config
- [ ] All 7 tests in test_r11c_config_scoring.py pass
- [ ] All 142 existing tests still pass
- [ ] No test file directly imports `_HIGH_IMPACT_RESOURCES`, `_HIGH_IMPACT_USERS`,
      or `_MED_IMPACT_RESOURCES` after this change

**Commit message:** `R11-C: config-driven scoring — lift hardcoded impact/likelihood constants to config.yaml`

---

## Part R11-D — Alert Deduplication and Detection Accuracy Fixes

### Why this exists

Four independent problems, each individually defensible in an interview, each fixable
in a small scope. They are grouped here because none requires a new phase on its own.

### D1 — Alert flooding in LogWatcher (standalone mode)

**The problem:** In `src/ingestion/watcher.py`, `_check_failed_logins` emits a new
violation dict every time the count exceeds the threshold. A 100-attempt brute force
generates ~98 near-identical violations. Your IR cites Oltsik (2017) on alert fatigue
as a core motivation. The live mode manufactures the problem it was built to solve.

**What to implement:**

Add a `_violation_cooldown: dict[str, datetime]` to `LogWatcher.__init__`:

```python
self._violation_cooldown: dict[str, datetime] = {}
```

In `_check_failed_logins`, before appending a violation, check whether a violation
for this `(username, source_host)` key was already emitted within the current window:

```python
from datetime import datetime

def _check_failed_logins(self, event: dict) -> list[dict]:
    cfg = self._config["detection"]["failed_logins"]
    threshold = cfg["threshold"]
    window = timedelta(minutes=cfg["time_window_minutes"])
    username = event["username"]
    source_host = event.get("source_host", "")
    ts = event["timestamp"]
    key = f"{source_host}:{username}"

    with self._lock:
        buf = self._failed_buffer.setdefault(key, deque())
        buf.append(ts)
        while buf and ts - buf[0] > window:
            buf.popleft()
        count = len(buf)

        if count > threshold:
            last_emitted = self._violation_cooldown.get(key)
            if last_emitted and ts - last_emitted < window:
                return []   # already reported this burst; suppress duplicate
            self._violation_cooldown[key] = ts
            return [{
                "violation_type": "failed_logins",
                "timestamp": ts,
                "username": username,
                "source_host": source_host,
                "source_ip": event.get("source_ip"),
                "resource": None,
                "detail": (
                    f"{count} failed logins in "
                    f"{cfg['time_window_minutes']} min for user '{username}'"
                ),
            }]
    return []
```

IMPORTANT: Update the `_failed_buffer` key from `username` to `f"{source_host}:{username}"`
throughout `LogWatcher` — otherwise violations from different source hosts for the same
username get mixed counts in standalone mode too.

**Tests:** Add to `tests/test_watcher.py`:
```
test_alert_flood_suppressed_within_window
    — 20 consecutive FAILED events for same user; assert on_violation called
      exactly ONCE (not 18 times)

test_alert_emitted_again_after_window_expires
    — first burst emits violation; second burst starts after window_minutes;
      assert on_violation called TWICE total
```

### D2 — Restricted resource matching uses exact match (URL prefix bug)

**The problem:** `/admin` is in `restricted_resources` but `/admin/`, `/admin/login.php`,
and `/admin?page=1` all pass through without detection. Real attacker probes use paths.

**What to implement:** In `src/detection/rules/unauthorized_access.py`, replace
the exact-match check with a prefix match:

```python
def _matches_restricted(resource: str, restricted: set) -> bool:
    """Return True if resource starts with any restricted prefix."""
    # Normalise: strip query string before matching
    path = resource.split("?")[0]
    # Strip trailing slashes for comparison
    path = path.rstrip("/") or "/"
    for prefix in restricted:
        clean_prefix = prefix.rstrip("/")
        if path == clean_prefix or path.startswith(clean_prefix + "/"):
            return True
    return False
```

Replace the existing match condition:
```python
# OLD:
and event.get("resource") in restricted
# NEW:
and _matches_restricted(event.get("resource", ""), restricted)
```

**Tests:** Add to `tests/test_detection.py`:
```
test_restricted_subpath_detected       — /admin/users triggers violation
test_restricted_query_string_detected  — /admin?page=1 triggers violation
test_exact_match_still_works           — /admin triggers violation
test_non_restricted_similar_name       — /administrator does NOT trigger violation
```

### D3 — Remove /var/www/html from default restricted_resources

**The problem:** `/var/www/html` is a filesystem path. It will never appear in an
HTTP request's resource field. Its presence in the default config makes the config
look wrong to anyone who reads it.

**What to implement:** Remove `/var/www/html` from `restricted_resources` in BOTH
`config/config.yaml` AND `config/config_default.yaml`. No other changes.

**Tests:** Add to `tests/test_detection.py`:
```
test_var_www_html_not_in_default_restricted_resources
    — load config/config_default.yaml; assert "/var/www/html" not in
      config["detection"]["unauthorized_access"]["restricted_resources"]
```

### D4 — Password spray detection by source IP

**The problem:** `detect_failed_logins` groups by `username` only. One source IP
making one attempt each against 50 different accounts produces zero violations.
Your IR explicitly cites T1110.003 (password spraying) and notes it "leaves footprints
when logs are reviewed collectively." The tool does not review them collectively.

**What to implement:** Add a second detection pass in
`src/detection/rules/failed_logins.py` after the existing username-based loop:

```python
def _detect_spray_by_ip(df: pd.DataFrame, threshold: int, window: pd.Timedelta) -> list[dict]:
    """
    Detect password spraying: one source IP targeting many distinct usernames.
    Threshold is reused as the minimum number of distinct usernames from one IP
    within the window to constitute a spray.
    """
    violations = []
    for source_ip, group in df.groupby("source_ip"):
        if pd.isna(source_ip) or source_ip == "":
            continue
        group = group.sort_values("timestamp").reset_index(drop=True)
        timestamps = group["timestamp"].tolist()
        usernames  = group["username"].tolist()

        left = 0
        max_distinct = 0
        max_left = 0
        for right in range(len(timestamps)):
            while timestamps[right] - timestamps[left] > window:
                left += 1
            distinct = len(set(usernames[left:right + 1]))
            if distinct > max_distinct:
                max_distinct = distinct
                max_left = left

        if max_distinct >= threshold:
            violations.append({
                "violation_type": "failed_logins",
                "timestamp": timestamps[max_left].to_pydatetime(),
                "username": None,                 # no single target username
                "source_ip": source_ip,
                "resource": None,
                "detail": (
                    f"Password spray: {max_distinct} distinct usernames "
                    f"targeted from {source_ip} within {window.seconds // 60} min"
                ),
            })
    return violations
```

Call this inside `detect_failed_logins` and merge results, deduplicating by source_ip
so the same spray doesn't appear twice:

```python
# After existing username-based detection:
spray_violations = _detect_spray_by_ip(df, threshold, window)

# Deduplicate: if source_ip already produced a per-username violation, skip spray entry
existing_ips = {v.get("source_ip") for v in violations}
for sv in spray_violations:
    if sv["source_ip"] not in existing_ips:
        violations.append(sv)
```

**Tests:** Add to `tests/test_detection.py`:
```
test_spray_across_multiple_usernames_detected
    — 5 FAILED events from same IP, each targeting a different username,
      within window; threshold=3; assert violation detected with
      violation_type="failed_logins" and "spray" in detail

test_spray_below_threshold_not_detected
    — 2 FAILED events from same IP, different usernames; threshold=3;
      assert no violation

test_spray_does_not_double_count_with_brute_force
    — same IP doing 5 fails on one username AND 5 fails on a second username;
      assert total violations <= 2 (not 4)
```

### Acceptance Criteria — R11-D

- [ ] LogWatcher emits at most ONE violation per (source_host, username) per window
- [ ] Alert flood test: 20 consecutive FAILEDs for same user → on_violation called once
- [ ] Alert re-emission test: second burst after window expiry → on_violation called twice
- [ ] `/admin/login.php` and `/admin?page=1` trigger unauthorized_access violations
- [ ] `/administrator` does NOT trigger unauthorized_access (prefix match, not substring)
- [ ] `/var/www/html` is NOT in config_default.yaml's restricted_resources
- [ ] Password spray across 5 usernames from one IP triggers a violation
- [ ] Password spray below threshold does not trigger
- [ ] All new tests (D1: 2, D2: 4, D3: 1, D4: 3) pass
- [ ] All 142 existing tests still pass

**Commit message:** `R11-D: dedup alerts, prefix resource matching, spray detection, remove /var/www/html`

---

## Part R11-E — Evaluation Artifacts (No Pipeline Code Changes)

### Why this exists

The project has no performance numbers, no measured detection accuracy, and no
labelled test confirming the system finds what it claims to find. An examiner
can currently ask "what is your false positive rate?" and the honest answer is
"unknown." R11-E closes that gap with minimal effort because you control the ground
truth of the synthetic log.

This part is primarily run by you (Mak), not Claude Code. CC produces scripts;
you execute them and record results.

### E1 — Fix simulate.py to produce all four tiers (REQUIRED — already on your list)

**The problem:** Your own PROGRESS notes confirm synthetic data only produces Medium
and High. A demo where Low (green) and Critical (dark red) cards never appear invites
"does the Critical path even work?"

**What Claude Code must do:**

Review `simulate.py` and verify all four tier patterns using current config.yaml
scoring rules. The existing comments claim:

```
Low      3 failed logins for guest        L=2 I=2  Score=4   ✓ Low
Medium   8 failed logins for hacker       L=3 I=2  Score=6   ✓ Medium
High     3 x GET /admin → 403             L=3 I=5  Score=15  ✓ High
Critical 20 failed logins for admin       L=5 I=4  Score=20  ✓ Critical
```

Verify these calculations are correct against the CURRENT scoring code (post R11-C).
If the scoring constants moved to config and the defaults changed, recalculate and
fix the simulate.py patterns until all four tiers actually appear.

Run `python simulate.py` followed by `python main.py --batch-only` (or equivalent
headless run that processes logs without opening the GUI), then query the database:

```sql
SELECT severity, COUNT(*) FROM risk_scores GROUP BY severity;
```

Expected output:
```
Low       | N >= 1
Medium    | N >= 1
High      | N >= 1
Critical  | N >= 1
```

If any tier is missing, adjust the violation count/username in simulate.py until
all four appear. Update the comments in simulate.py to show the corrected calculations.

**Acceptance Criteria for E1:**
- [ ] `python simulate.py` followed by a batch pipeline run produces at least one
      violation in each of the four severity tiers
- [ ] simulate.py comments correctly document the L × I calculation for each pattern

### E2 — Labelled detection accuracy test

**What Claude Code must produce:**

Create `tests/test_r11e_accuracy.py`. This is a ground-truth test: you know exactly
what violations should be detected from a known log, and the test asserts they all are.

The test must:
1. Build a labelled synthetic auth.log in memory (not written to disk) with exactly:
   - 20 FAILED logins for user `root` from `10.0.0.1` within 5 minutes  → 1 brute force
   - 3 FAILED logins for user `guest` from `10.0.0.2` within 5 minutes  → 1 brute force
   - 1 FAILED login for user `nobody` (below threshold)                  → no violation
   - 1 SUCCESSFUL login for user `alice` at 03:00 on a Monday             → 1 off-hours
   - 1 SUCCESSFUL login for user `bob` at 10:00 on a Monday              → no violation
2. Build a labelled access.log with exactly:
   - 5 GET /admin requests returning 403 from `10.0.0.3`                 → 1 unauth
   - 3 GET /about requests returning 200 from `10.0.0.4`                 → no violation
3. Run the full pipeline (preprocess → detect → score) on these in-memory lines
4. Assert:
   - Exactly 3 violations detected (brute_force_root, brute_force_guest, unauth_admin,
     off_hours_alice) — actually 4; count them precisely
   - Each has the correct violation_type
   - root brute force severity is Critical (score >= 17)
   - guest brute force severity is Low or Medium (score <= 9)
   - unauth admin severity is High (score >= 10)
   - off_hours alice severity is Medium (score <= 9)
   - The undetected cases (nobody, bob, /about) produce zero violations
5. Assert that the false positive count is zero (no violations for the known-clean inputs)

This test is deterministic, requires no database, and runs in ~100ms. It serves as
a confusion-matrix substitute for the FYP report.

**Acceptance Criteria for E2:**
- [ ] `tests/test_r11e_accuracy.py` exists and passes
- [ ] The ground-truth test detects exactly the expected violations
- [ ] Zero false positives on known-clean inputs
- [ ] All 142 existing tests still pass alongside the new accuracy test

### E3 — Performance benchmark script

**What Claude Code must produce:**

Create `scripts/benchmark.py`. This script is NOT part of the test suite — it is
a standalone measurement script you run manually and record results from.

The script must:
1. Load `logs/real/SSH_2k.log` and `logs/real/Apache_2k.log`
2. Time the full pipeline run (ingest → detect → score) using `time.perf_counter()`
3. Print the following report:
   ```
   === CyberMon Performance Benchmark ===
   Log files processed     : SSH_2k.log (2000 lines), Apache_2k.log (2000 lines)
   Total lines attempted   : 4000
   Lines parsed            : XXXX (XX.X%)
   Events normalised       : XXXX
   Pipeline execution time : X.XXX seconds
   Processing rate         : XXXX events/second
   Violations detected     : XX (breakdown by type below)
     failed_logins         : XX
     unauthorized_access   : XX
     off_hours_login       : XX
   Database write time     : X.XXX seconds
   Total time (incl. DB)   : X.XXX seconds
   DB size after run       : X.X KB
   ```
4. Use a TEMPORARY database (not `data/cybermon.db`) — create in `tmp/` and delete
   after the benchmark run is complete
5. Exit with code 0 on success

**You run this script, record the output, and add one table to the FYP report
(Implementation chapter) titled "Pipeline Performance on Real Log Data."**

Expected results: on a typical laptop, 4000 lines should process in under 3 seconds.
If it takes longer, report that honestly — it is still useful data.

**Acceptance Criteria for E3:**
- [ ] `scripts/benchmark.py` exists and runs without errors
- [ ] Benchmark output matches the format above
- [ ] Temporary database is cleaned up after run
- [ ] You have run it and recorded the output (results go in REWORK_PROGRESS.md,
      not in this file)

### E4 — Parse rate confirmation for IR

The REWORK_PROGRESS.md from Phase R0 should already contain parse rates for SSH_2k.log
and Apache_2k.log. Verify those numbers are still accurate after the parser changes
in R11-D (prefix matching in `unauthorized_access.py` does not affect the parser,
but double-check).

**What Claude Code must do:**
1. Run `scripts/benchmark.py` (created in E3)
2. Confirm parse rates match what is recorded in REWORK_PROGRESS.md from R0
3. If they differ, update REWORK_PROGRESS.md

---

## Full Acceptance Criteria — All of R11

When all four parts are complete, the following must ALL be true:

### Security
- [ ] POST /ingest requires X-API-Key header; missing or wrong key → 401
- [ ] Payload > 2MB → 413; batch > 5000 lines → 413
- [ ] Host field validated against safe characters; invalid → 400
- [ ] CyberMonAgent sends API key on every POST
- [ ] RUNNING.md documents the shared-key setup and its limitations

### Network mode detection correctness
- [ ] Slow brute force (1 event per batch) detected after 2nd batch in network mode
- [ ] Events outside time window excluded from count
- [ ] Duplicate violations suppressed within window

### Scoring configurability
- [ ] No hardcoded user/resource lists in scoring/rules.py
- [ ] Changing high_impact_users in config.yaml changes scores without code edits
- [ ] Settings panel exposes user/resource lists for editing

### Detection accuracy
- [ ] LogWatcher alert flood suppressed — 20 FAILEDs → 1 violation, not 18
- [ ] /admin/login.php triggers unauthorized_access
- [ ] /administrator does NOT trigger unauthorized_access
- [ ] /var/www/html not in default config
- [ ] Password spray across 5 usernames from one IP detected
- [ ] Ground-truth accuracy test passes with zero false positives

### Test suite
- [ ] Total test count: 142 (existing) + 10 (R11-A) + 8 (R11-B) + 7 (R11-C) + 10 (R11-D) + 1 (R11-E) = 178 tests
- [ ] All 178 tests pass with `python -m pytest tests/ -q`

### Evaluation artifacts
- [ ] simulate.py produces all four severity tiers
- [ ] scripts/benchmark.py exists and runs cleanly
- [ ] Benchmark results recorded in REWORK_PROGRESS.md
- [ ] test_r11e_accuracy.py passes (ground-truth detection test)

---

## REWORK_PROGRESS.md Entry Template for R11

Add the following block to REWORK_PROGRESS.md before starting:

```markdown
### Phase R11 — Hardening and Evaluation
**Status:** Not started
**Date Started:**
**Date Completed:**

#### Part R11-A: Ingest Endpoint Auth
**Status:** Not started
**Tests added:** 10 (test_r11a_auth.py)
**Tests passing:** / 178
**Commit hash:**

#### Part R11-B: Stateful Failed-Login Detection
**Status:** Not started
**Tests added:** 8 (test_r11b_stateful_detection.py + integration)
**Tests passing:** / 178
**Commit hash:**

#### Part R11-C: Config-Driven Scoring
**Status:** Not started
**Tests added:** 7 (test_r11c_config_scoring.py)
**Tests passing:** / 178
**Commit hash:**

#### Part R11-D: Detection Accuracy Fixes
**Status:** Not started
**Tests added:** 10 (split across test_detection.py and test_watcher.py)
**Tests passing:** / 178
**Commit hash:**

#### Part R11-E: Evaluation Artifacts
**Status:** Not started
**Benchmark results:**
  - Lines attempted: 4000
  - Lines parsed: TBD
  - Parse rate: TBD%
  - Pipeline time: TBDs
  - Events/second: TBD
  - Violations detected: TBD
  - DB size: TBD KB
**test_r11e_accuracy.py:** Not run
**simulate.py four-tier check:** Not run
**Commit hash:**
```

---

## Summary Table

| Part | What It Fixes | Tests Added | Complexity | Time Estimate |
|------|--------------|-------------|------------|---------------|
| R11-A | Ingest auth (kill-shot) | 10 | Low | ~2 hours |
| R11-B | Network mode slow brute force | 8 | Medium | ~3 hours |
| R11-C | Config-driven scoring (claim vs reality) | 7 | Medium | ~3 hours |
| R11-D | Alert flood, prefix match, spray, cleanup | 10 | Medium | ~3 hours |
| R11-E | Accuracy test, benchmark, tier fix | 1 + scripts | Low | ~2 hours |
| **Total** | | **36 new tests** | | **~13 hours** |
