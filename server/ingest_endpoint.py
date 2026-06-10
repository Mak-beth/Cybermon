"""CyberMon ingest endpoint — receives log lines from remote agents.

Completely separate Flask app instance from the dashboard (src/dashboard/app.py).
Only route: POST /ingest.

This separation ensures the ingest server survives independently when the
dashboard is replaced in R3 with a PyQt6 GUI.
"""
import os
import re

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
# Security — shared API key, payload limits, host identifier validation
# ---------------------------------------------------------------------------

# Loaded once at import; config load on every request is too slow.
# Tests override this module-level variable directly.
try:
    _EXPECTED_KEY = _load_config().get("server", {}).get("api_key", "")
except (OSError, yaml.YAMLError):
    _EXPECTED_KEY = ""

_MAX_BODY_BYTES = 2 * 1024 * 1024   # 2MB request body cap
_MAX_BATCH_LINES = 5000             # max lines per POST
_HOST_RE = re.compile(r'^[\w\.\-]{1,64}$')


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

    Returns HTTP 401 if the X-API-Key header is missing or wrong,
    HTTP 413 if the payload exceeds size limits, and
    HTTP 400 if the body is missing, not JSON, or lacks required keys.
    """
    # --- Authentication — checked before any body processing ---
    received_key = request.headers.get("X-API-Key", "")
    if not received_key or received_key != _EXPECTED_KEY:
        return jsonify({"error": "unauthorized"}), 401

    # --- Payload size cap (before JSON parse) ---
    if request.content_length and request.content_length > _MAX_BODY_BYTES:
        return jsonify({"error": "payload too large"}), 413

    body = request.get_json(silent=True)

    # --- Validation ---
    if body is None:
        return jsonify({"error": "request body must be JSON"}), 400
    if "host" not in body or "lines" not in body:
        return jsonify({"error": "'host' and 'lines' are required"}), 400
    if not isinstance(body["lines"], list):
        return jsonify({"error": "'lines' must be a list"}), 400
    if len(body["lines"]) > _MAX_BATCH_LINES:
        return jsonify(
            {"error": f"batch too large — max {_MAX_BATCH_LINES} lines per request"}
        ), 413

    host = str(body["host"])
    if not _HOST_RE.match(host):
        return jsonify({"error": "invalid host identifier"}), 400

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
    from src.detection.rules.failed_logins import detect_failed_logins_from_db
    from src.detection.rules.unauthorized_access import detect_unauthorized_access
    from src.detection.rules.off_hours import detect_off_hours_logins
    from src.scoring.scorer import score_all_violations
    from src.storage.db import init_db
    from src.storage.writer import (
        insert_events, insert_violation, insert_risk_score,
        find_triggering_event_id,
    )

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

    # Detect and score.  Failed logins are stateful: the rule queries the DB
    # for the full time window so slow brute forces spread across many small
    # batches are still caught.  The other two rules are self-contained per
    # event, so batch-only detection is correct for them.
    failed_login_violations = detect_failed_logins_from_db(
        events, config, db_path, host
    )
    unauth_violations = detect_unauthorized_access(events, config)
    off_hours_violations = detect_off_hours_logins(events, config)

    violations = failed_login_violations + unauth_violations + off_hours_violations
    scored = score_all_violations(violations, config)

    for v in scored:
        v["source_host"] = host                                 # tag with agent host
        v["triggering_event_id"] = find_triggering_event_id(v, db_path)
        vid = insert_violation(v, db_path)
        insert_risk_score(vid, v, db_path)

    return jsonify({"received": len(lines), "violations_detected": len(scored)}), 200
