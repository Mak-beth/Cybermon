"""Recompute risk scores for violations already in the database.

Why this exists
---------------
Scoring values (likelihood/impact) are editable from the Settings panel. Without
this, a change only took effect after restarting the app, because the pipeline
re-derives everything from the log files at launch.

This recompute is deliberately NARROW: it re-scores the violations that are
already stored, in place. It never re-reads log files, never clears tables, and
never runs detection. That means:

  * events and violations rows are untouched — no inserts, no deletes, no id
    changes. Only values in risk_scores are updated.
  * DETECTION changes (thresholds, business hours, restricted resources, log
    paths) are NOT reflected — those change which violations exist, which only a
    full pipeline run at startup can do. Callers must say so in the UI.

Scoring logic itself is unchanged: this calls the existing score_violation().
"""
from __future__ import annotations

import logging
import sqlite3

from src.scoring.scorer import score_violation

logger = logging.getLogger(__name__)

# Columns score_violation() needs; timestamp is carried for completeness.
_VIOLATION_COLUMNS = (
    "id", "violation_type", "timestamp", "username",
    "source_ip", "resource", "detail", "source_host",
)


def rescore_violations(db_path: str, config: dict) -> dict:
    """Re-score every stored violation using `config`.

    Runs as a single transaction: if anything fails, nothing is committed and
    the previous scores remain intact.

    Returns a summary dict::

        {"total": <violations seen>, "updated": <risk_scores rows written>,
         "changed": <rows whose score actually differs>}
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    total = updated = changed = 0
    try:
        cur = conn.cursor()
        rows = cur.execute(
            f"SELECT {', '.join(_VIOLATION_COLUMNS)} FROM violations"
        ).fetchall()

        for row in rows:
            total += 1
            violation = dict(row)
            violation_id = violation["id"]

            scored = score_violation(violation, config)
            new = (
                scored["likelihood"], scored["impact"],
                scored["risk_score"], scored["severity"],
            )

            existing = cur.execute(
                "SELECT likelihood, impact, risk_score, severity "
                "FROM risk_scores WHERE violation_id = ?",
                (violation_id,),
            ).fetchone()

            if existing is None:
                # A violation with no score row (shouldn't normally happen).
                # Create one so it is not left unscored; still risk_scores-only.
                cur.execute(
                    "INSERT INTO risk_scores (violation_id, likelihood, impact, "
                    "risk_score, severity, source_host) VALUES (?, ?, ?, ?, ?, ?)",
                    (violation_id, *new, violation.get("source_host") or "localhost"),
                )
                updated += 1
                changed += 1
                continue

            if tuple(existing) != new:
                changed += 1
            cur.execute(
                "UPDATE risk_scores SET likelihood = ?, impact = ?, "
                "risk_score = ?, severity = ? WHERE violation_id = ?",
                (*new, violation_id),
            )
            updated += 1

        conn.commit()
    except (sqlite3.Error, KeyError, TypeError, ValueError):
        conn.rollback()
        logger.exception("rescore: failed; no scores were changed")
        raise
    finally:
        conn.close()

    logger.info(
        "rescore: %d violation(s) re-scored, %d score(s) changed", total, changed
    )
    return {"total": total, "updated": updated, "changed": changed}
