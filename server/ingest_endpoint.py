"""CyberMon ingest endpoint — receives log lines from remote agents.

Completely separate Flask app instance from the dashboard (src/dashboard/app.py).
Only route: POST /ingest.

This separation ensures the ingest server survives independently when the
dashboard is replaced in R3 with a PyQt6 GUI.
"""
import os

import yaml
from flask import Flask, jsonify, request

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_BASE_DIR = os.path.abspath(os.path.join(_HERE, ".."))

# ---------------------------------------------------------------------------
# Flask app — fresh instance, no shared state with dashboard
# ---------------------------------------------------------------------------
ingest_app = Flask(__name__)


def _load_config() -> dict:
    """Load config.yaml from the project root."""
    path = os.path.join(_BASE_DIR, "config", "config.yaml")
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@ingest_app.route("/ingest", methods=["POST"])
def ingest():
    """Receive a batch of raw log lines from a CyberMonAgent.

    Expected JSON body::

        {"host": "hostname", "lines": ["line1", "line2", ...]}

    Returns::

        {"received": N, "violations_detected": M}

    Returns HTTP 400 if the body is missing, not JSON, or lacks required keys.
    """
    body = request.get_json(silent=True)

    # --- Validation ---
    if body is None:
        return jsonify({"error": "request body must be JSON"}), 400
    if "host" not in body or "lines" not in body:
        return jsonify({"error": "'host' and 'lines' are required"}), 400
    if not isinstance(body["lines"], list):
        return jsonify({"error": "'lines' must be a list"}), 400

    host = str(body["host"])
    lines = body["lines"]

    if not lines:
        return jsonify({"received": 0, "violations_detected": 0}), 200

    # --- Pipeline ---
    config = _load_config()
    raw_db_path = config["storage"]["db_path"]
    # Support both relative (to project root) and absolute paths
    db_path = (
        raw_db_path if os.path.isabs(raw_db_path)
        else os.path.join(_BASE_DIR, raw_db_path)
    )

    from src.ingestion.parser import parse_auth_log_line, parse_access_log_line
    from src.ingestion.preprocessor import normalize_event
    from src.detection.detector import run_detection
    from src.scoring.scorer import score_all_violations
    from src.storage.db import init_db
    from src.storage.writer import insert_events, insert_violation, insert_risk_score

    init_db(db_path)

    # Parse each line — try auth parser first, fall back to web parser
    events = []
    for line in lines:
        parsed = parse_auth_log_line(line)
        log_type = "auth"
        if parsed is None:
            parsed = parse_access_log_line(line)
            log_type = "web"
        if parsed is not None:
            event = normalize_event(parsed, log_type)
            event["source_host"] = host   # override with agent-supplied host ID
            events.append(event)

    if events:
        insert_events(events, db_path)

    # Detect and score on this batch
    violations = run_detection(events, config)
    scored = score_all_violations(violations, config)

    for v in scored:
        v["source_host"] = host           # tag violation with agent host
        vid = insert_violation(v, db_path)
        insert_risk_score(vid, v, db_path)

    return jsonify({"received": len(lines), "violations_detected": len(scored)}), 200
