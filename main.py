import argparse
import logging
import os
import shutil
import sqlite3
import sys
import threading
import time
import yaml

# ---------------------------------------------------------------------------
# Path helpers — must be defined before anything that uses them (incl. logging)
# ---------------------------------------------------------------------------

def _resource_path(relative: str) -> str:
    """Absolute path to a READ-ONLY bundled resource.

    In a PyInstaller onefile build, sys._MEIPASS is the temp extraction
    directory where frozen data files are unpacked.
    In development it is the project root.
    """
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative)


def _data_path(relative: str) -> str:
    """Absolute path to a WRITABLE runtime file (config, database, logs).

    In a PyInstaller onefile build these files live NEXT TO the .exe
    (sys.executable), not inside the temp extraction dir.
    In development it is the project root.
    """
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(os.path.dirname(sys.executable), relative)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative)


# ---------------------------------------------------------------------------
# Logging — file next to the exe in production, project root in development
# ---------------------------------------------------------------------------

logging.basicConfig(
    filename=_data_path("cybermon.log"),
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s",
)

from src.ingestion.preprocessor import preprocess_log_file
from src.detection.detector import run_detection
from src.scoring.scorer import score_all_violations
from src.storage.db import init_db
from src.storage.writer import (
    insert_events,
    insert_violation,
    insert_risk_score,
    find_triggering_event_id,
)
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

    init_db(db_path)
    _clear_tables(db_path)

    print("[ 1/5 ] Ingesting logs...")
    events = (preprocess_log_file(auth_log, "auth") +
              preprocess_log_file(web_log, "web"))
    print(f"        {len(events)} events parsed")

    insert_events(events, db_path)

    print("[ 2/5 ] Running detection...")
    violations = run_detection(events, config)
    print(f"        {len(violations)} violations detected")

    print("[ 3/5 ] Scoring violations...")
    scored = score_all_violations(violations, config)

    print("[ 4/5 ] Storing results...")
    for v in scored:
        v["triggering_event_id"] = find_triggering_event_id(v, db_path)
        vid = insert_violation(v, db_path)
        insert_risk_score(vid, v, db_path)

    summary = get_summary_counts(db_path)
    print("[ 5/5 ] Done.\n")
    print("=== Cybermon Summary ===")
    print(f"  Events parsed    : {len(events)}")
    print(f"  Violations found : {summary['total']}")
    print(f"  By type          : {dict(summary['by_type'])}")
    print(f"  By severity      : {dict(summary['by_severity'])}")

    return {"events": events, "scored": scored, "summary": summary}


def _start_ingest_server(config: dict) -> None:
    """Start the ingest endpoint on a daemon thread (network mode only)."""
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
    time.sleep(1)


def _is_first_run(config_path: str) -> bool:
    """Return True when the wizard has never been completed."""
    if not os.path.exists(config_path):
        return True
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}
    return not cfg.get("setup_complete", False)


def main():
    parser = argparse.ArgumentParser(description="Cybermon - security log analysis pipeline")
    parser.add_argument("--auth-log", default=None, help="Path to Linux auth log file")
    parser.add_argument("--web-log",  default=None, help="Path to Apache access log file")
    args = parser.parse_args()

    # 1. Resolve writable config path (next to exe in production).
    config_path = _data_path("config/config.yaml")

    # 2. Bootstrap: copy bundled factory-default config on a clean install.
    if not os.path.exists(config_path):
        default_src = _resource_path("config/config_default.yaml")
        if os.path.exists(default_src):
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            shutil.copy2(default_src, config_path)

    # 3. Load config.
    if os.path.exists(config_path):
        config = yaml.safe_load(open(config_path)) or {}
    else:
        config = {}

    # 4. Resolve db_path to absolute so SQLite always finds it regardless of CWD.
    raw_db = config.get("storage", {}).get("db_path", "data/cybermon.db")
    if not os.path.isabs(raw_db):
        config.setdefault("storage", {})["db_path"] = _data_path(raw_db)
    # Ensure the data directory exists.
    os.makedirs(os.path.dirname(config["storage"]["db_path"]), exist_ok=True)

    # 5. Qt imports inside main() so `from main import run_pipeline` in tests
    #    never triggers Qt at import time.
    from PyQt6.QtWidgets import QApplication, QDialog
    app = QApplication(sys.argv)

    # 6. First-run: show setup wizard before anything else.
    if _is_first_run(config_path):
        from src.gui.wizard import SetupWizard
        wizard = SetupWizard(config, config_path=config_path)
        if wizard.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)
        config = yaml.safe_load(open(config_path)) or {}
        raw_db = config.get("storage", {}).get("db_path", "data/cybermon.db")
        if not os.path.isabs(raw_db):
            config.setdefault("storage", {})["db_path"] = _data_path(raw_db)

    mode = config.get("mode", "standalone")

    # 7. Determine log paths.
    auth_log = args.auth_log or config.get("auth_log_path", _data_path("logs/samples/auth.log"))
    web_log  = args.web_log  or config.get("web_log_path",  _data_path("logs/samples/access.log"))

    # 8. Run pipeline (errors are shown in the GUI, never crash the app).
    pipeline_error: str | None = None
    try:
        run_pipeline(auth_log, web_log, config)
    except Exception as exc:
        logging.exception("Pipeline error during startup")
        pipeline_error = str(exc)

    # 9. Start continuous live monitoring.
    from src.ingestion.watcher import LogWatcher

    def _live_event_sink(event: dict, db_path: str) -> None:
        """Persist each live event exactly like the batch pipeline does.

        Runs before detection, so a violation's triggering_event_id resolves to
        a real row and the detail view can show the raw log excerpt.

        Note: live mode runs continuously, so the events table grows for as long
        as the app is running. That is accepted here — there is deliberately no
        retention/pruning logic.
        """
        try:
            insert_events([event], db_path)
        except Exception as exc:
            logging.getLogger(__name__).error("Live event sink error: %s", exc)

    def _live_callback(scored_violation: dict, db_path: str) -> None:
        try:
            scored_violation["triggering_event_id"] = find_triggering_event_id(
                scored_violation, db_path
            )
            vid = insert_violation(scored_violation, db_path)
            insert_risk_score(vid, scored_violation, db_path)
        except Exception as exc:
            logging.getLogger(__name__).error("Live callback error: %s", exc)

    db_path = config["storage"]["db_path"]
    watcher = LogWatcher(config)
    watcher.start(
        auth_log=auth_log,
        web_log=web_log,
        on_violation=lambda v: _live_callback(v, db_path),
        on_event=lambda e: _live_event_sink(e, db_path),
    )

    # 10. Network mode: ingest endpoint on a daemon thread.
    if mode == "network":
        _start_ingest_server(config)

    # 11. Launch desktop window.
    from src.gui.main_window import MainWindow

    window = MainWindow(config)
    window.show()

    if pipeline_error:
        window.show_error_banner(pipeline_error)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
