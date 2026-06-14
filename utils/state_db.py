"""
UTIL: State Database
PURPOSE: SQLite persistence for processed URLs and cron state
"""

import sqlite3
import json
from datetime import datetime, timezone
from utils.config import DATA_DIR
from utils.logger import log_debug

DB_PATH = f"{DATA_DIR}/newsbot.db"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS processed_urls (
                url TEXT PRIMARY KEY,
                source TEXT,
                title TEXT,
                processed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS cron_state (
                source TEXT PRIMARY KEY,
                last_check TEXT,
                extra TEXT
            );
        """)
        conn.commit()
    log_debug("State DB initialized")


def is_url_processed(url: str) -> bool:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_urls WHERE url = ?", (url,)
        ).fetchone()
        return row is not None


def mark_url_processed(url: str, source: str, title: str = ""):
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO processed_urls (url, source, title, processed_at) VALUES (?, ?, ?, ?)",
            (url, source, title, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def get_cron_state(source: str) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM cron_state WHERE source = ?", (source,)).fetchone()
        if row:
            data = dict(row)
            if data.get("extra"):
                data["extra"] = json.loads(data["extra"])
            return data
        return None


def set_cron_state(source: str, last_check: str, extra: dict | None = None):
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO cron_state (source, last_check, extra) VALUES (?, ?, ?)",
            (source, last_check, json.dumps(extra) if extra else None),
        )
        conn.commit()
