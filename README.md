# Cybermon

A rule-based cybersecurity monitoring tool that ingests log files, detects policy violations, scores risk, and presents findings via a web dashboard.

## Stack

- **Python 3.10+**
- **pandas** — event grouping and time-window analysis
- **PyYAML** — config loading
- **Flask** — web dashboard
- **SQLite** — local persistence
- **pytest** — unit and integration tests

## How to Run

```bash
# 1. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS

# 2. Install dependencies
pip install -r requirements.txt

# 3. Verify config loads
python main.py

# 4. Run full pipeline (after all phases complete)
python main.py

# 5. Run tests
pytest tests/ -v
```

## Project Structure

```
cybermon/
├── config/config.yaml        # All thresholds and settings
├── data/                     # SQLite database (auto-created)
├── exports/                  # CSV exports
├── logs/samples/             # Synthetic test log files
├── src/
│   ├── ingestion/            # Log reading, parsing, normalizing
│   ├── detection/            # Rule-based violation detection
│   ├── scoring/              # Likelihood x impact risk scoring
│   ├── storage/              # SQLite persistence layer
│   └── dashboard/            # Flask web dashboard
├── tests/                    # Unit and integration tests
├── main.py                   # Pipeline entry point
├── requirements.txt
├── PHASES.md                 # Static implementation plan
└── PROGRESS.md               # Living progress log
```

## Phases

| Phase | Deliverable |
|-------|-------------|
| 0 | Scaffold |
| 1 | Log ingestion + preprocessing |
| 2 | Violation detection engine |
| 3 | Risk scoring |
| 4 | Storage layer |
| 5 | Flask dashboard |
| 6 | Integration, testing, UAT |
