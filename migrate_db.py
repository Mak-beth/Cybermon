"""CyberMon database migration script.

Adds new columns to an existing database without dropping data.
Safe to run multiple times — each column is only added if it is absent.

Usage:
    python migrate_db.py                       # migrates data/cybermon.db
    python migrate_db.py path/to/other.db
"""
import sqlite3
import sys

# Each entry: (table, column_name, column_definition)
_MIGRATIONS = [
    # R1 — source host tagging
    ("events",      "source_host",          "TEXT NOT NULL DEFAULT 'localhost'"),
    ("violations",  "source_host",          "TEXT NOT NULL DEFAULT 'localhost'"),
    ("risk_scores", "source_host",          "TEXT NOT NULL DEFAULT 'localhost'"),
    # R5 — raw log line storage and triggering event FK
    ("events",      "raw_log",              "TEXT"),
    ("violations",  "triggering_event_id",  "INTEGER"),
]


def migrate(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    for table, column, definition in _MIGRATIONS:
        cur.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cur.fetchall()}
        if column not in existing:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )
            print(f"  {table}.{column}: added")
        else:
            print(f"  {table}.{column}: already present — skipped")

    conn.commit()
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/cybermon.db"
    print(f"Migrating {path} ...")
    migrate(path)
