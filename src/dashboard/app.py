import sys
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import csv
import json
import queue
from datetime import date

import yaml
from flask import Flask, jsonify, render_template, send_file, abort, Response, stream_with_context

from src.storage.db import init_db
from src.storage.reader import (
    get_all_violations_with_scores,
    get_summary_counts,
    get_violation_detail,
    get_trend_data,
    get_trend_by_hour_today,
)

app = Flask(__name__, template_folder="templates", static_folder="static")

_config = yaml.safe_load(open(os.path.join(BASE_DIR, "config", "config.yaml")))
DB_PATH = os.path.join(BASE_DIR, _config["storage"]["db_path"])
EXPORT_DIR = os.path.join(BASE_DIR, _config["dashboard"]["export_path"])

init_db(DB_PATH)

_violation_queue: queue.Queue = queue.Queue()

# Sentinel: put on the queue to stop the generator (used by tests only).
_SSE_STOP = object()


def post_violation(v: dict) -> None:
    _violation_queue.put(v)


def _sse_generator(q: queue.Queue):
    try:
        while True:
            try:
                v = q.get(timeout=30)
                if v is _SSE_STOP:
                    return
                yield f"data: {json.dumps(v, default=str)}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"
    except GeneratorExit:
        pass


@app.route("/")
def index():
    summary = get_summary_counts(DB_PATH)
    return render_template("index.html", summary=summary)


@app.route("/violations")
def violations():
    rows = get_all_violations_with_scores(DB_PATH)
    return render_template("violations.html", violations=rows)


RECOMMENDED_RESPONSE = {
    'Low':      'Log and monitor. No immediate action required.',
    'Medium':   'Review and investigate at next available opportunity.',
    'High':     'Investigate promptly. Consider temporary account lock.',
    'Critical': 'Immediate investigation and escalation required.',
}


@app.route("/violations/<int:id>")
def violation_detail(id):
    detail = get_violation_detail(id, DB_PATH)
    if not detail:
        abort(404)
    recommended = RECOMMENDED_RESPONSE.get(detail['severity'], '')
    return render_template("detail.html", violation=detail, recommended=recommended)


@app.errorhandler(404)
def not_found(e):
    return "Violation not found.", 404


@app.route("/trend")
def trend():
    trend_data = get_trend_by_hour_today(DB_PATH)
    return render_template("trend.html", trend_data=trend_data)


@app.route("/export")
def export():
    rows = get_all_violations_with_scores(DB_PATH)
    filename = f"cybermon_report_{date.today().isoformat()}.csv"
    os.makedirs(EXPORT_DIR, exist_ok=True)
    filepath = os.path.join(EXPORT_DIR, filename)

    headers = ["id", "violation_type", "timestamp", "username", "source_ip",
               "resource", "detail", "likelihood", "impact", "risk_score", "severity"]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    return send_file(filepath, as_attachment=True, download_name=filename)


@app.route("/api/summary")
def api_summary():
    summary = get_summary_counts(DB_PATH)
    return jsonify(summary)


@app.route("/stream")
def stream():
    resp = Response(
        stream_with_context(_sse_generator(_violation_queue)),
        mimetype="text/event-stream",
    )
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@app.route("/live")
def live():
    violations = get_all_violations_with_scores(DB_PATH)
    return render_template("live.html", violations=violations)


if __name__ == "__main__":
    app.run(
        host=_config["dashboard"]["host"],
        port=_config["dashboard"]["port"],
        debug=_config["dashboard"]["debug"],
    )
