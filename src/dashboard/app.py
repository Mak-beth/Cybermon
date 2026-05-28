import sys
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import csv
from datetime import date

import yaml
from flask import Flask, render_template, send_file, abort

from src.storage.db import init_db
from src.storage.reader import (
    get_all_violations_with_scores,
    get_summary_counts,
    get_violation_detail,
    get_trend_data,
)

app = Flask(__name__, template_folder="templates", static_folder="static")

_config = yaml.safe_load(open(os.path.join(BASE_DIR, "config", "config.yaml")))
DB_PATH = os.path.join(BASE_DIR, _config["storage"]["db_path"])
EXPORT_DIR = os.path.join(BASE_DIR, _config["dashboard"]["export_path"])

init_db(DB_PATH)


@app.route("/")
def index():
    summary = get_summary_counts(DB_PATH)
    return render_template("index.html", summary=summary)


@app.route("/violations")
def violations():
    rows = get_all_violations_with_scores(DB_PATH)
    return render_template("violations.html", violations=rows)


@app.route("/violations/<int:id>")
def violation_detail(id):
    detail = get_violation_detail(id, DB_PATH)
    if not detail:
        abort(404)
    return render_template("detail.html", violation=detail)


@app.errorhandler(404)
def not_found(e):
    return "Violation not found.", 404


@app.route("/trend")
def trend():
    data = get_trend_data(DB_PATH, days=7)
    labels = [entry["date"] for entry in data]
    counts = [entry["count"] for entry in data]
    return render_template("trend.html", labels=labels, counts=counts)


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


if __name__ == "__main__":
    app.run(
        host=_config["dashboard"]["host"],
        port=_config["dashboard"]["port"],
        debug=_config["dashboard"]["debug"],
    )
