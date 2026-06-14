"""
UTIL: Notion Client
PURPOSE: CRUD operations for the NMD News Channel Posts database
"""

import requests
from datetime import datetime, timezone
from utils.config import NOTION_API_KEY, NOTION_DATABASE_ID
from utils.logger import log_info, log_error

BASE_URL = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def url_exists(url: str) -> bool:
    """Check if a URL already exists in the database."""
    try:
        resp = requests.post(
            f"{BASE_URL}/databases/{NOTION_DATABASE_ID}/query",
            headers=HEADERS,
            json={
                "filter": {
                    "property": "Source url",
                    "url": {"equals": url},
                }
            },
            timeout=30,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return len(results) > 0
    except Exception as e:
        log_error(f"Notion url_exists error: {e}")
        return False


def create_post(
    title: str,
    post_text: str,
    source_url: str,
    article_date: str,
    summary: str = "",
    status: str = "Sent for approval",
    post_type: str = "News",
) -> dict:
    """Create a new database entry. Returns the created page."""
    # Notion rich_text fields have a 2000 char limit; titles can be up to 2000 as well
    MAX_TEXT = 1990
    safe_title = (title[:MAX_TEXT] + "…") if len(title) > MAX_TEXT else title
    safe_post = (post_text[:MAX_TEXT] + "…") if len(post_text) > MAX_TEXT else post_text
    safe_summary = (summary[:MAX_TEXT] + "…") if (summary and len(summary) > MAX_TEXT) else summary

    body = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Title": {"title": [{"text": {"content": safe_title}}]},
            "Post text": {"rich_text": [{"text": {"content": safe_post}}]},
            "Source url": {"url": source_url},
            "Date": {"date": {"start": article_date}},
            "Status": {"select": {"name": status}},
            "Type": {"select": {"name": post_type}},
        },
    }
    if safe_summary:
        body["properties"]["Summary"] = {"rich_text": [{"text": {"content": safe_summary}}]}

    resp = requests.post(f"{BASE_URL}/pages", headers=HEADERS, json=body, timeout=30)
    if resp.status_code == 400:
        log_error(f"Notion 400 for '{title}': {resp.text[:600]}")
    resp.raise_for_status()
    log_info(f"Notion row created: {title}")
    return resp.json()


def update_post_status(page_id: str, status: str, post_url: str = "") -> dict:
    """Update Status and optionally Post url."""
    body = {
        "properties": {
            "Status": {"select": {"name": status}},
        }
    }
    if post_url:
        body["properties"]["Post url"] = {"url": post_url}

    resp = requests.patch(f"{BASE_URL}/pages/{page_id}", headers=HEADERS, json=body, timeout=30)
    resp.raise_for_status()
    log_info(f"Notion row updated: {page_id} → {status}")
    return resp.json()


def get_page_by_id(page_id: str) -> dict | None:
    """Fetch a single page by ID. Returns dict with title, post_text, status, source_url."""
    try:
        resp = requests.get(f"{BASE_URL}/pages/{page_id}", headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        props = data.get("properties", {})

        # Extract title
        title = ""
        t = props.get("Title", {}).get("title", [])
        if t:
            title = t[0].get("text", {}).get("content", "")

        # Extract post_text
        post_text = ""
        pt = props.get("Post text", {}).get("rich_text", [])
        if pt:
            post_text = pt[0].get("text", {}).get("content", "")

        # Extract status
        status = ""
        sel = props.get("Status", {}).get("select")
        if sel:
            status = sel.get("name", "")

        # Extract source_url
        source_url = ""
        url_prop = props.get("Source url", {}).get("url")
        if url_prop:
            source_url = url_prop

        return {
            "title": title,
            "post_text": post_text,
            "status": status,
            "source_url": source_url,
        }
    except Exception as e:
        log_error(f"Notion get_page_by_id error ({page_id}): {e}")
        return None


def get_recent_posts(days: int = 3) -> list[dict]:
    """Fetch posts from last N days for duplicate checking."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        resp = requests.post(
            f"{BASE_URL}/databases/{NOTION_DATABASE_ID}/query",
            headers=HEADERS,
            json={
                "filter": {
                    "property": "Date",
                    "date": {"after": cutoff},
                },
                "page_size": 100,
            },
            timeout=30,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        posts = []
        for r in results:
            props = r.get("properties", {})
            title = ""
            t = props.get("Title", {}).get("title", [])
            if t:
                title = t[0].get("text", {}).get("content", "")
            pt = props.get("Post text", {}).get("rich_text", [])
            post_text = pt[0].get("text", {}).get("content", "") if pt else ""
            posts.append({"title": title, "post_text": post_text})
        return posts
    except Exception as e:
        log_error(f"Notion get_recent_posts error: {e}")
        return []
