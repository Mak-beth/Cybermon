import os
import sqlite3


def init_db(db_path: str) -> None:
    dir_name = os.path.dirname(db_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            username    TEXT,
            source_ip   TEXT,
            resource    TEXT,
            action      TEXT,
            status_code TEXT,
            log_type    TEXT,
            source_host TEXT NOT NULL DEFAULT 'localhost',
            raw_log     TEXT
        );

        CREATE TABLE IF NOT EXISTS violations (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            violation_type       TEXT NOT NULL,
            timestamp            TEXT NOT NULL,
            username             TEXT,
            source_ip            TEXT,
            resource             TEXT,
            detail               TEXT,
            source_host          TEXT NOT NULL DEFAULT 'localhost',
            triggering_event_id  INTEGER
        );

        CREATE TABLE IF NOT EXISTS risk_scores (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            violation_id INTEGER NOT NULL,
            likelihood   INTEGER NOT NULL,
            impact       INTEGER NOT NULL,
            risk_score   INTEGER NOT NULL,
            severity     TEXT NOT NULL,
            source_host  TEXT NOT NULL DEFAULT 'localhost',
            FOREIGN KEY (violation_id) REFERENCES violations(id)
        );
    """)
    conn.commit()
    conn.close()
