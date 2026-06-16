"""
UTIL: State Database
PURPOSE: SQLite persistence for processed URLs, cron state, and posts
"""

import sqlite3
import uuid
import json
from datetime import datetime, timezone, timedelta
from utils.config import DATA_DIR
from utils.logger import log_debug, log_info, log_error

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
            CREATE TABLE IF NOT EXISTS pending_images (
                page_id TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS posts (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                post_text TEXT NOT NULL,
                summary TEXT DEFAULT '',
                source_url TEXT NOT NULL,
                article_date TEXT DEFAULT '',
                status TEXT DEFAULT 'Sent for approval',
                post_type TEXT DEFAULT 'News',
                post_url TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
            CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at);
            CREATE INDEX IF NOT EXISTS idx_posts_source_url ON posts(source_url);
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


def save_image_file_id(page_id: str, file_id: str):
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pending_images (page_id, file_id, created_at) VALUES (?, ?, ?)",
            (page_id, file_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def get_image_file_id(page_id: str) -> str | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT file_id FROM pending_images WHERE page_id = ?", (page_id,)
        ).fetchone()
        return row["file_id"] if row else None


def delete_image_file_id(page_id: str):
    with _get_conn() as conn:
        conn.execute("DELETE FROM pending_images WHERE page_id = ?", (page_id,))
        conn.commit()


# ── Posts (replaces Notion) ────────────────────────────────────


def url_exists(url: str) -> bool:
    """Check if a URL was already processed (processed_urls or posts table)."""
    with _get_conn() as conn:
        if conn.execute("SELECT 1 FROM processed_urls WHERE url = ?", (url,)).fetchone():
            return True
        return conn.execute("SELECT 1 FROM posts WHERE source_url = ?", (url,)).fetchone() is not None


def create_post(
    title: str,
    post_text: str,
    source_url: str,
    article_date: str = "",
    summary: str = "",
    status: str = "Sent for approval",
    post_type: str = "News",
) -> dict:
    """Insert a new post row. Returns {"id": uuid_str} to match old Notion interface."""
    post_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO posts (id, title, post_text, summary, source_url, article_date,
               status, post_type, post_url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?)""",
            (post_id, title, post_text, summary, source_url, article_date, status, post_type, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO processed_urls (url, source, title, processed_at) VALUES (?, ?, ?, ?)",
            (source_url, "posts", title, now),
        )
        conn.commit()
    log_info(f"Post created in DB: {title[:60]}")
    return {"id": post_id}


def get_page_by_id(post_id: str) -> dict | None:
    """Fetch a post by ID. Returns dict with title, post_text, status, source_url."""
    try:
        with _get_conn() as conn:
            row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
            if not row:
                return None
            return {
                "title": row["title"],
                "post_text": row["post_text"],
                "status": row["status"],
                "source_url": row["source_url"],
            }
    except Exception as e:
        log_error(f"get_page_by_id error ({post_id}): {e}")
        return None


def update_post_status(post_id: str, status: str, post_url: str = "") -> None:
    """Update a post's status and optionally its published URL."""
    with _get_conn() as conn:
        conn.execute(
            "UPDATE posts SET status = ?, post_url = ? WHERE id = ?",
            (status, post_url, post_id),
        )
        conn.commit()
    log_info(f"Post status updated: {post_id} → {status}")


def get_stale_pending_posts(hours: int = 48) -> list[dict]:
    """Return posts stuck in 'Sent for approval' older than `hours` hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id FROM posts WHERE status = 'Sent for approval' AND created_at < ?",
            (cutoff,),
        ).fetchall()
    return [{"id": row["id"]} for row in rows]


def archive_post(post_id: str) -> bool:
    """Delete a stale post from the DB."""
    try:
        with _get_conn() as conn:
            conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
            conn.commit()
        log_info(f"Stale post deleted: {post_id}")
        return True
    except Exception as e:
        log_error(f"archive_post error ({post_id}): {e}")
        return False


def get_recent_posts(days: int = 3) -> list[dict]:
    """Return posts from the last N days for duplicate detection."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT title, post_text FROM posts WHERE created_at > ? ORDER BY created_at DESC LIMIT 100",
            (cutoff,),
        ).fetchall()
    return [{"title": row["title"], "post_text": row["post_text"]} for row in rows]
