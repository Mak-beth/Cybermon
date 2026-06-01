"""One-time migration: adds source_host column to an existing CyberMon database.

Usage:
    python migrate_db.py                       # migrates data/cybermon.db
    python migrate_db.py path/to/other.db
"""
import sqlite3
import sys


def migrate(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    for table in ("events", "violations", "risk_scores"):
        cur.execute(f"PRAGMA table_info({table})")
        existing_cols = {row[1] for row in cur.fetchall()}
        if "source_host" not in existing_cols:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN "
                f"source_host TEXT NOT NULL DEFAULT 'localhost'"
            )
            print(f"  {table}: added source_host")
        else:
            print(f"  {table}: source_host already present — skipped")

    conn.commit()
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/cybermon.db"
    print(f"Migrating {path} ...")
    migrate(path)
