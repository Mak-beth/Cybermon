import argparse
import sqlite3
import sys
import threading
import time
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


def _start_ingest_server(config: dict) -> None:
    """Start the ingest endpoint on a daemon thread (network mode only).

    Uses a completely separate Flask app instance so it survives independently
    when the dashboard is replaced by PyQt6 in R3.
    """
    from server.ingest_endpoint import ingest_app

    ingest_host = config["server"]["host"]
    ingest_port = config["server"]["port"]

    t = threading.Thread(
        target=lambda: ingest_app.run(
            host=ingest_host,
            port=ingest_port,
            debug=False,
            use_reloader=False,
            threaded=True,
        ),
        daemon=True,
        name="ingest-endpoint",
    )
    t.start()
    print(f"\nIngest endpoint -> http://{ingest_host}:{ingest_port}/ingest")

    # Give the ingest server time to bind its socket before the Qt window starts.
    time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="Cybermon — security log analysis pipeline")
    parser.add_argument("--auth-log", default="logs/samples/auth.log",
                        help="Path to Linux auth log file")
    parser.add_argument("--web-log", default="logs/samples/access.log",
                        help="Path to Apache access log file")
    args = parser.parse_args()

    # 1. Load config
    config = yaml.safe_load(open("config/config.yaml"))
    mode = config.get("mode", "standalone")

    # 2. Run ingestion + detection + scoring pipeline
    run_pipeline(args.auth_log, args.web_log, config)

    # 3. Network mode: start ingest endpoint on a background daemon thread.
    #    Standalone mode: ingest endpoint is not started.
    if mode == "network":
        _start_ingest_server(config)

    # 4. Launch the PyQt6 desktop window.
    #    Imports are inside main() so that `from main import run_pipeline`
    #    in tests never triggers Qt at import time.
    from PyQt6.QtWidgets import QApplication
    from src.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
