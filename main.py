import argparse
import sqlite3
import yaml

from src.ingestion.preprocessor import preprocess_log_file
from src.detection.detector import run_detection
from src.scoring.scorer import score_all_violations
from src.storage.db import init_db
from src.storage.writer import insert_events, insert_violation, insert_risk_score
from src.storage.reader import get_summary_counts


def _clear_tables(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        DELETE FROM risk_scores;
        DELETE FROM violations;
        DELETE FROM events;
        DELETE FROM sqlite_sequence WHERE name IN ('risk_scores', 'violations', 'events');
    """)
    conn.commit()
    conn.close()


def run_pipeline(auth_log: str, web_log: str, config: dict) -> dict:
    db_path = config["storage"]["db_path"]

    # 2. Init DB
    init_db(db_path)
    _clear_tables(db_path)

    # 3. Ingest
    print("[ 1/5 ] Ingesting logs...")
    events = (preprocess_log_file(auth_log, "auth") +
              preprocess_log_file(web_log, "web"))
    print(f"        {len(events)} events parsed")

    # 4. Store events
    insert_events(events, db_path)

    # 5. Detect
    print("[ 2/5 ] Running detection...")
    violations = run_detection(events, config)
    print(f"        {len(violations)} violations detected")

    # 6. Score
    print("[ 3/5 ] Scoring violations...")
    scored = score_all_violations(violations, config)

    # 7. Store violations and scores
    print("[ 4/5 ] Storing results...")
    for v in scored:
        vid = insert_violation(v, db_path)
        insert_risk_score(vid, v, db_path)

    # 8. Print summary
    summary = get_summary_counts(db_path)
    print("[ 5/5 ] Done.\n")
    print("=== Cybermon Summary ===")
    print(f"  Events parsed    : {len(events)}")
    print(f"  Violations found : {summary['total']}")
    print(f"  By type          : {dict(summary['by_type'])}")
    print(f"  By severity      : {dict(summary['by_severity'])}")

    return {"events": events, "scored": scored, "summary": summary}


def main():
    parser = argparse.ArgumentParser(description="Cybermon — security log analysis pipeline")
    parser.add_argument("--auth-log", default="logs/samples/auth.log",
                        help="Path to Linux auth log file")
    parser.add_argument("--web-log", default="logs/samples/access.log",
                        help="Path to Apache access log file")
    args = parser.parse_args()

    # 1. Load config
    config = yaml.safe_load(open("config/config.yaml"))

    run_pipeline(args.auth_log, args.web_log, config)

    # 9. Launch dashboard
    host = config["dashboard"]["host"]
    port = config["dashboard"]["port"]
    print(f"\nLaunching dashboard → http://{host}:{port}")
    print("Press Ctrl+C to stop.\n")

    from src.dashboard.app import app
    app.run(host=host, port=port, debug=config["dashboard"]["debug"])


if __name__ == "__main__":
    main()
