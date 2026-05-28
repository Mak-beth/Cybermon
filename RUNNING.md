# Running Cybermon

Step-by-step instructions for getting the project running locally.
Updated after each phase. Current state: **Phase 5 complete**.

---

## Prerequisites

- Python 3.10 or later
- Git

Verify with:
```
py --version
git --version
```

---

## 1. Clone the repository

```bash
git clone https://github.com/Mak-beth/Cybermon.git
cd Cybermon
```

---

## 2. Create and activate the virtual environment

```bash
py -m venv venv
venv\Scripts\activate
```

Your prompt should now show `(venv)`.

---

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

Installs: `flask`, `pandas`, `pyyaml`, `pytest`.

---

## 4. Verify config loads (Phase 0 check)

```bash
venv\Scripts\python.exe main.py
```

Expected output:

```
=== Cybermon Config ===
Failed login threshold : 5
Time window (min)      : 10
...
Config loaded successfully.
```

---

## 5. Run the test suite (Phases 1–4)

```bash
venv\Scripts\pytest.exe tests/ -v
```

Expected: **87 tests, all passing** across `test_ingestion.py`, `test_detection.py`, `test_scoring.py`, `test_storage.py`.

---

## 6. Populate the database (required before launching dashboard)

Run this once to ingest the synthetic logs, detect violations, score them, and write everything to `data/cybermon.db`:

```bash
venv\Scripts\python.exe -c "
import yaml, os
from src.ingestion.preprocessor import preprocess_log_file
from src.detection.detector import run_detection
from src.scoring.scorer import score_all_violations
from src.storage.db import init_db
from src.storage.writer import insert_events, insert_violation, insert_risk_score

config = yaml.safe_load(open('config/config.yaml'))
db_path = config['storage']['db_path']

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

print(f'Done: {len(events)} events, {len(scored)} violations stored.')
"
```

Expected output: `Done: 47 events, 12 violations stored.`

> **Note:** Phase 6 will replace this step with a single `python main.py` command.

---

## 7. Launch the dashboard (Phase 5)

```bash
venv\Scripts\python.exe src\dashboard\app.py
```

Then open your browser at:

| URL | Page |
|-----|------|
| `http://127.0.0.1:5000/` | Overview — total count, severity chart |
| `http://127.0.0.1:5000/violations` | Ranked violation list |
| `http://127.0.0.1:5000/violations/1` | Single violation detail |
| `http://127.0.0.1:5000/trend` | Violations over time |
| `http://127.0.0.1:5000/export` | Download CSV report |

Press `Ctrl+C` to stop the server.

---

## Configuration

All thresholds and settings live in `config/config.yaml`. No values are hardcoded in source files.

| Setting | Default | Effect |
|---------|---------|--------|
| `detection.failed_logins.threshold` | 5 | Minimum failures in window to trigger alert |
| `detection.failed_logins.time_window_minutes` | 10 | Rolling window size |
| `detection.unauthorized_access.trigger_codes` | [403, 401] | HTTP status codes that count as unauthorised |
| `dashboard.port` | 5000 | Port the Flask server listens on |

---

## Phase completion status

| Phase | What it adds | How to run |
|-------|-------------|------------|
| 0 | Scaffold, config | `python main.py` |
| 1 | Log ingestion | `pytest tests/test_ingestion.py -v` |
| 2 | Violation detection | `pytest tests/test_detection.py -v` |
| 3 | Risk scoring | `pytest tests/test_scoring.py -v` |
| 4 | SQLite storage | `pytest tests/test_storage.py -v` |
| 5 | Flask dashboard | `python src/dashboard/app.py` |
| 6 | Full pipeline (`main.py`) | `python main.py` *(not yet implemented)* |
