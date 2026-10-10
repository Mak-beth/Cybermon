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


def _prepare_database(config: dict) -> None:
    """Create the schema, then apply storage.clear_on_start.

    Called once from main() at startup, whether or not pipeline.run_on_launch
    lets run_pipeline() run.

    Demo-rebuild design: each launch reflects the log files as they are now, so
    the tables are emptied on launch. Set storage.clear_on_start to false in
    config.yaml to accumulate findings across sessions instead. The schema and
    the database file persist either way.
    A missing key means true, so an older config keeps the previous behaviour.
    """
    db_path = config["storage"]["db_path"]
    init_db(db_path)
    if config.get("storage", {}).get("clear_on_start", True):
        _clear_tables(db_path)


def run_pipeline(auth_log: str, web_log: str, config: dict) -> dict:
    db_path = config["storage"]["db_path"]

    init_db(db_path)

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


def _run_on_launch(config: dict) -> bool:
    """True unless pipeline.run_on_launch is explicitly false.

    A missing key (or a missing/empty pipeline block) means true, so an older
    config keeps the previous read-everything-at-startup behaviour.
    """
    return bool((config.get("pipeline") or {}).get("run_on_launch", True))


def _is_first_run(config_path: str) -> bool:
    """Return True when the wizard has never been completed."""
    if not os.path.exists(config_path):
        return True
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}
    return not cfg.get("setup_complete", False)


# Stable taskbar identity for dev-mode runs (python main.py). Windows groups
# taskbar buttons by AppUserModelID; a script otherwise inherits python.exe's
# identity and icon, whatever setWindowIcon() says. The packaged exe already
# has its own identity, so it is left alone.
_APP_USER_MODEL_ID = "CyberMon.SecurityMonitoring.1"


def _set_windows_app_id() -> None:
    """Give a dev-mode run CyberMon's own taskbar identity.

    Windows only, and skipped in the packaged exe. Must run before any window
    exists.
    """
    if sys.platform != "win32" or hasattr(sys, "_MEIPASS"):
        return
    try:
        import ctypes
        hr = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        logging.exception("Could not set the Windows AppUserModelID")
        return
    if hr != 0:
        logging.error(
            "SetCurrentProcessExplicitAppUserModelID failed (HRESULT %#010x)",
            hr & 0xFFFFFFFF,
        )


def _apply_app_icon(app) -> None:
    """Use assets/icon.ico, the file the exe build embeds, as the app-wide icon.

    Does nothing when the file isn't there: the packaged exe carries the icon
    only as its embedded resource, not as a data file, so the exe is unchanged.
    """
    icon_path = _resource_path("assets/icon.ico")
    if not os.path.isfile(icon_path):
        return
    from PyQt6.QtGui import QIcon
    app.setWindowIcon(QIcon(icon_path))


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
    # The taskbar identity must be set before any window exists.
    _set_windows_app_id()
    from PyQt6.QtWidgets import QApplication, QDialog
    app = QApplication(sys.argv)
    _apply_app_icon(app)

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

    # 8. Prepare the database, then run the pipeline (errors are shown in the GUI,
    #    never crash the app). Schema creation and the clear_on_start wipe run on
    #    every launch; pipeline.run_on_launch only decides whether the startup
    #    batch read follows. The live watcher below starts either way.
    pipeline_error: str | None = None
    try:
        _prepare_database(config)
        if _run_on_launch(config):
            run_pipeline(auth_log, web_log, config)
        else:
            print("[ skip ] pipeline.run_on_launch is false - startup ingestion skipped.")
    except Exception as exc:
        logging.exception("Pipeline error during startup")
        pipeline_error = str(exc)

    # 9. Start continuous live monitoring. LiveMonitor owns the watcher and its
    #    database callbacks, so Settings can switch log files mid-session.
    from src.live_monitor import LiveMonitor

    monitor = LiveMonitor(config, db_path=config["storage"]["db_path"])
    monitor.start(auth_log, web_log)

    # 10. Network mode: ingest endpoint on a daemon thread.
    if mode == "network":
        _start_ingest_server(config)

    # 11. Launch desktop window.
    from src.gui.main_window import MainWindow

    # config_path is passed explicitly so Settings edits the same file main()
    # loaded; monitor lets Settings restart live monitoring on new log paths.
    window = MainWindow(config, config_path=config_path, monitor=monitor)
    window.show()

    if pipeline_error:
        window.show_error_banner(pipeline_error)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
