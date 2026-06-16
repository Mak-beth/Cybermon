# Running CyberMon

How to install and run CyberMon in both deployment modes.

CyberMon has two modes, set by the `mode:` key in `config/config.yaml`:

- **Standalone** — one machine reads its own log files. No network setup.
- **Network** — a central machine runs CyberMon (GUI + ingest server); one or
  more **agents** on other machines tail their logs and POST new lines to it.

The mode is chosen in the setup wizard on first launch, or by editing
`config/config.yaml` directly. There is **no command-line flag** for mode — it is
config-driven.

---

## Contents

1. [Prerequisites](#1-prerequisites)
2. [Install from source](#2-install-from-source)
3. [Standalone mode](#3-standalone-mode)
4. [Generating demo data](#4-generating-demo-data)
5. [Network mode — concepts](#5-network-mode--concepts)
6. [Network mode — server setup](#6-network-mode--server-setup)
7. [Network mode — agent setup](#7-network-mode--agent-setup)
8. [Multiple agents / multiple hosts](#8-multiple-agents--multiple-hosts)
9. [Network mode security](#9-network-mode-security)
10. [Application panels](#10-application-panels)
11. [Configuration reference](#11-configuration-reference)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Prerequisites

- Windows 10/11
- Python 3.12 (only needed to run from source — the packaged `.exe` needs nothing)
- Git

```powershell
py --version
git --version
```

End users who only have the packaged build (`CyberMon.exe`, `CyberMonAgent.exe`)
do **not** need Python — skip to the mode sections and substitute the `.exe` for
the `python ...` commands.

---

## 2. Install from source

```powershell
git clone https://github.com/Mak-beth/Cybermon.git
cd Cybermon

py -m venv venv
venv\Scripts\activate          # prompt now shows (venv)

pip install -r requirements.txt
```

Installs: `PyQt6`, `PyQtGraph`, `flask`, `pandas`, `pyyaml`, `requests`, `pytest`.

Run the test suite to confirm a clean install:

```powershell
venv\Scripts\python.exe -m pytest tests/ -q
```

Expected: **179 tests passing**.

---

## 3. Standalone mode

This is the default. One machine, reading its own log files.

```powershell
venv\Scripts\python.exe main.py
```

Or double-click `start.bat`, which creates the venv, installs dependencies, and
launches the app.

**First launch** shows a 3-screen setup wizard:

| Screen | What to do |
|--------|-----------|
| Mode | Choose **"Just this computer"** (standalone) |
| Configuration | Set log file paths, business hours, brute-force threshold |
| Confirmation | Review and click **Finish** |

The main window then opens. On every later launch the wizard is skipped (a
`setup_complete: true` key in `config.yaml` records that it ran).

Point the pipeline at your own logs without editing config:

```powershell
venv\Scripts\python.exe main.py --auth-log C:\path\to\auth.log --web-log C:\path\to\access.log
```

---

## 4. Generating demo data

To see violations across all four severity tiers without real attack traffic,
run the simulator. It appends synthetic log lines to the paths configured in
`config.yaml` (`auth_log_path` / `web_log_path`):

```powershell
venv\Scripts\python.exe simulate.py
```

It produces:

| Tier | Pattern | Score |
|------|---------|-------|
| Low | 3 failed logins for `guest_HHMMSS` (unique per run) | 4 |
| Medium | 8 failed logins for `hacker` | 6 |
| High | 3 × GET /admin returning 403 | 15 |
| Critical | 20 failed logins for `admin` | 20 |

With the app already running, new violations appear in the Live Feed within a
few seconds (the `LogWatcher` tails the configured files continuously).

To confirm all four tiers landed in the database:

```powershell
venv\Scripts\python.exe scripts\tier_check.py
```

---

## 5. Network mode — concepts

```
  Agent machine 1                       Server machine
  ┌─────────────────┐                   ┌────────────────────────────┐
  │ CyberMonAgent   │  POST /ingest     │ CyberMon (main.py)         │
  │ tails auth.log  │ ────────────────▶ │  • ingest server :5001     │
  │ host_id=web-01  │  X-API-Key        │  • detection + scoring     │
  └─────────────────┘                   │  • SQLite + PyQt6 GUI      │
  ┌─────────────────┐                   │                            │
  │ CyberMonAgent   │ ────────────────▶ │  violations tagged with    │
  │ host_id=db-02   │                   │  each agent's host_id      │
  └─────────────────┘                   └────────────────────────────┘
```

- The **server** is the normal CyberMon app running with `mode: network`. It
  opens the GUI *and* starts an HTTP ingest endpoint on port `5001` (a daemon
  thread). There is no separate headless server process.
- Each **agent** is `CyberMonAgent` (`agent_main.py`). It tails one log file and
  POSTs new lines to the server as `{"host": host_id, "lines": [...]}` with an
  `X-API-Key` header.
- The server runs every received batch through the same detection and scoring
  pipeline and tags each violation with the agent's `host_id`. Failed-login
  detection in network mode is stateful (it queries the full time window from
  the database), so a slow brute force spread across many small batches is still
  caught.

---

## 6. Network mode — server setup

On the machine that will collect logs:

1. Put the app into network mode. Either choose **"Monitor multiple computers"**
   in the setup wizard, or edit `config/config.yaml`:

   ```yaml
   mode: network
   server:
     host: 0.0.0.0                       # listen on all interfaces
     port: 5001
     api_key: "choose-a-long-random-string"   # agents must send this
   ```

2. Find this machine's LAN IP (agents will need it):

   ```powershell
   ipconfig    # note the IPv4 address, e.g. 192.168.1.10
   ```

3. Start the server:

   ```powershell
   venv\Scripts\python.exe main.py
   ```

   The GUI opens and the console prints:
   `Ingest endpoint -> http://0.0.0.0:5001/ingest`

4. If Windows Firewall prompts, allow Python/CyberMon on **private networks** so
   agents can reach port 5001.

---

## 7. Network mode — agent setup

On each machine you want to monitor (or, for testing, in another terminal on the
same machine — see section 8):

1. First run creates `agent_config.yaml` with defaults next to the agent:

   ```powershell
   venv\Scripts\python.exe agent_main.py
   ```

   It prints where it wrote the file, then exits-ish into its tail loop.

2. Edit `agent_config.yaml` so it points at the server and matches its key:

   ```yaml
   server_ip: 192.168.1.10          # the server's LAN IP (127.0.0.1 if same machine)
   server_port: 5001
   log_path: logs/auth.log          # the log this agent should tail
   host_id: web-01                  # how this machine appears in the dashboard
   api_key: "choose-a-long-random-string"   # MUST match the server's server.api_key
   retry_attempts: 3
   retry_delay_seconds: 2
   ```

3. Start the agent:

   ```powershell
   venv\Scripts\python.exe agent_main.py
   ```

   A console window stays open showing status:
   `Watching logs/auth.log` / `Posting to http://192.168.1.10:5001/ingest as host 'web-01'`.
   When new lines are written to the log, the agent prints one line per batch
   sent. Violations show up in the server's GUI tagged `web-01`.

> The agent only sends lines written **after** it starts (it seeks to the end of
> the file on open). Append new lines, or run `simulate.py` against the file the
> agent is tailing, to produce traffic.

If the server rejects the key you'll see:
`FATAL: server rejected API key` — fix `api_key` in `agent_config.yaml` to match
the server's `server.api_key` and restart.

---

## 8. Multiple agents / multiple hosts

You can monitor several machines by running one agent per machine (section 7 on
each). You can also **simulate multiple hosts from a single laptop** by running
several agents in parallel, each with its own config and `host_id`. The server
cannot tell the two situations apart — it only sees POSTs carrying different host
identifiers.

Each agent reads its config from `--config` (defaults to `agent_config.yaml`).
Give each one a separate file:

1. Make a config per simulated host:

   ```powershell
   Copy-Item agent_config.yaml agent_host1.yaml
   Copy-Item agent_config.yaml agent_host2.yaml
   ```

2. Edit them so they differ in `host_id` and `log_path` (and both match the
   server's `api_key`):

   ```yaml
   # agent_host1.yaml
   host_id: "laptop-A"
   log_path: "logs/host1/auth.log"
   api_key: "choose-a-long-random-string"
   server_ip: "127.0.0.1"
   server_port: 5001
   ```
   ```yaml
   # agent_host2.yaml
   host_id: "laptop-B"
   log_path: "logs/host2/auth.log"
   api_key: "choose-a-long-random-string"
   server_ip: "127.0.0.1"
   server_port: 5001
   ```

3. Run three terminals, each with the venv activated:

   ```powershell
   # Terminal 1 — server (config.yaml has mode: network)
   venv\Scripts\python.exe main.py

   # Terminal 2 — agent simulating host A
   venv\Scripts\python.exe agent_main.py --config agent_host1.yaml

   # Terminal 3 — agent simulating host B
   venv\Scripts\python.exe agent_main.py --config agent_host2.yaml
   ```

4. Generate traffic for each host by appending failed-login lines to its log
   file. For example, a brute-force burst for `laptop-A`:

   ```powershell
   $ts = Get-Date -Format "MMM dd HH:mm:ss"
   1..6 | ForEach-Object {
     Add-Content logs/host1/auth.log "$ts server sshd[$_]: Failed password for root from 10.0.0.1 port 22 ssh2"
   }
   ```

   Do the same against `logs/host2/auth.log` for `laptop-B`. The dashboard now
   shows violations tagged with both `laptop-A` and `laptop-B`, exercising the
   full multi-host path — ingestion, stateful per-`(host, user)` detection, and
   alert dedup — without a second machine.

> **For your report / viva — be precise about what this proves.** Running
> multiple agents on one laptop demonstrates that the *software* handles multiple
> hosts correctly. It does **not** prove real cross-machine networking (firewall
> traversal, binding on `0.0.0.0`, a real LAN IP rather than `127.0.0.1`,
> separate NICs). Arrange at least one genuine two-laptop run before submission
> as validation evidence, and describe both honestly: the single-laptop
> multi-agent setup is the everyday development/demo method; the one real
> two-machine run is the networking proof.

All agents append to a shared `agent.log`; rely on each terminal's own console
output for per-agent status.

---

## 9. Network mode security

The ingest endpoint authenticates every agent with a shared API key sent in the
`X-API-Key` header. Requests without a matching key are rejected with HTTP 401.

**Set the key before any real deployment:**

1. On the server, set `server.api_key` in `config/config.yaml`.
2. On each agent, set `api_key` in its config file.
3. The two values must match exactly. Restart both sides after changing them.

The default value `CHANGE_ME_BEFORE_DEPLOY` is intentionally obvious — replace it
with a long random string.

**Known limitations:**

- Traffic is plaintext HTTP. On untrusted networks, run the agents and server
  over a VPN or a dedicated management VLAN. TLS is future work.
- The `host_id` an agent reports is validated (max 64 chars; letters, digits,
  dot, hyphen, underscore) but trusted — a compromised agent can still misreport
  its identity.
- Request bodies are capped at 2 MB and 5000 lines per batch to limit flooding.

---

## 10. Application panels

The sidebar switches between five panels:

| Panel | What it shows |
|-------|--------------|
| Overview | Five metric cards, severity doughnut, per-type breakdown bars (refreshes every 3 s) |
| Violations | Sortable table, colour-coded severity badges, host filter, Export CSV |
| Live Feed | New violations as they are detected; Pause / Resume / Clear |
| Trend | Line charts — violations by hour today and by day over the last 7 days |
| Settings | Edit log paths, business hours, thresholds, risk-scoring rules; toggle theme; re-run wizard |

**Export CSV:** in the Violations panel, set the host filter if needed and click
**Export CSV**. Columns: `timestamp`, `violation_type`, `source_host`,
`likelihood`, `impact`, `risk_score`, `severity`, `recommended_action`,
`log_excerpt`.

---

## 11. Configuration reference

All settings live in `config/config.yaml` (created by the wizard on first run).
Changes take effect on the next pipeline run or log scan. The Settings panel
edits the same file.

| Setting | Default | Effect |
|---------|---------|--------|
| `mode` | `standalone` | `standalone` or `network` |
| `ui.theme` | `light` | `light` or `dark` |
| `server.host` / `server.port` | `0.0.0.0` / `5001` | Ingest endpoint bind address (network mode) |
| `server.api_key` | `CHANGE_ME_BEFORE_DEPLOY` | Shared secret agents must match |
| `detection.failed_logins.threshold` | `2` | Failures in window before an alert fires |
| `detection.failed_logins.time_window_minutes` | `10` | Rolling window size |
| `detection.unauthorized_access.restricted_resources` | `/admin`, … | Path prefixes that trigger on 4xx |
| `detection.off_hours_logins.business_hours_start` / `_end` | `08:00` / `18:00` | Business-hours window |
| `scoring.severity_tiers` | Low 1–4 … Critical 17–25 | Score → severity bands |
| `scoring.rules` | see file | Editable impact/likelihood lists (R11-C) |
| `storage.db_path` | `data/cybermon.db` | SQLite database location |

Agent settings live separately in each agent's config (`agent_config.yaml` or a
`--config` file): `server_ip`, `server_port`, `log_path`, `host_id`, `api_key`,
`retry_attempts`, `retry_delay_seconds`.

---

## 12. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Agent prints `FATAL: server rejected API key` | `api_key` mismatch — make the agent's key equal the server's `server.api_key`, restart |
| Agent prints `Connection error … retrying` then drops the batch | Server not running, wrong `server_ip`/`server_port`, or firewall blocking port 5001 |
| Agent prints `WARNING: no api_key configured` | The agent config has an empty `api_key`; set it to match the server |
| No violations appear from an agent | The agent only sends lines written *after* it starts; append new lines or run `simulate.py` against the tailed file |
| Wizard reappears every launch | `setup_complete: true` is missing from `config.yaml` — finish the wizard, or set it manually |
| `python` not found | Use the launcher `py`, or `venv\Scripts\python.exe` directly |
| Tests fail after editing `config.yaml` | Several tests read the real `config/config.yaml`; restore defaults with `git checkout -- config/config.yaml` |

---

## Running from source — developer reference

```powershell
# Full pipeline against custom logs
venv\Scripts\python.exe main.py --auth-log path\to\auth.log --web-log path\to\access.log

# Run a single test module
venv\Scripts\python.exe -m pytest tests/test_detection.py -v

# Pipeline performance benchmark (real LogHub data, temp DB)
venv\Scripts\python.exe scripts\benchmark.py

# Agent help (including --config)
venv\Scripts\python.exe agent_main.py --help
```
