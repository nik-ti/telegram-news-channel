"""
NODE: Fetch RSS
PURPOSE: Poll RSS feeds and return new articles
INPUT: None
OUTPUT: List of article dicts {title, url, text, date, source}
DEPENDENCIES: feedparser, requests

NOTE: Always fetches raw XML via requests first (with explicit timeout),
then parses with feedparser. Never calls feedparser.parse(url) directly,
because urllib (used internally) has no reliable timeout and can hang
indefinitely, blocking the asyncio event loop.
"""

import email.utils
import feedparser
import io
import requests
from calendar import timegm
from datetime import datetime, timezone, timedelta
from utils.config import SOURCES, PROXY_SERVER, PROXY_PORT, PROXY_USERNAME, PROXY_PASSWORD
from utils.state_db import get_cron_state, set_cron_state, is_url_processed, mark_url_processed
from utils.logger import log_info, log_error

MAX_PER_SOURCE = 3       # max articles per source per cycle
MAX_AGE_DAYS = 1         # skip articles older than this (24 hours)

RSS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _parse_rfc_date(date_str: str) -> datetime | None:
    """Parse RFC 2822 date string to datetime."""
    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _entry_timestamp(entry) -> float:
    """Get Unix timestamp from feedparser entry."""
    time_tuple = entry.get("published_parsed") or entry.get("updated_parsed")
    if time_tuple:
        return timegm(time_tuple)
    # Fallback: parse raw date strings
    for field in ("published", "updated"):
        val = entry.get(field, "")
        if val:
            dt = _parse_rfc_date(val)
            if dt:
                return dt.timestamp()
    return 0.0


def _format_iso_date(dt: datetime) -> str:
    """Format datetime as YYYY-MM-DD for Notion."""
    return dt.strftime("%Y-%m-%d")


def _build_proxy_dict() -> dict:
    """Return requests-compatible proxy dict if credentials are set."""
    if PROXY_SERVER and PROXY_PORT:
        proxy_url = f"http://{PROXY_USERNAME}:{PROXY_PASSWORD}@{PROXY_SERVER}:{PROXY_PORT}"
        return {"http": proxy_url, "https": proxy_url}
    return {}


def _fetch_feed_xml(url: str, use_proxy: bool = False) -> bytes | None:
    """Fetch raw RSS XML with a realistic User-Agent and strict timeout."""
    proxies = _build_proxy_dict() if use_proxy else {}
    try:
        resp = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": RSS_USER_AGENT},
            proxies=proxies,
        )
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        log_error(f"RSS fetch error for {url}: {e}")
        return None


def fetch_feed(source_name: str, feed_url: str, use_proxy: bool = False) -> list[dict]:
    articles = []
    try:
        # Always fetch via requests first — never feedparser.parse(url)
        xml_bytes = _fetch_feed_xml(feed_url, use_proxy)
        if xml_bytes is None:
            log_error(f"RSS {source_name}: failed to fetch feed XML, skipping")
            return []

        parsed = feedparser.parse(io.BytesIO(xml_bytes))

        state = get_cron_state(f"rss_{source_name}") or {}
        extra = state.get("extra", {}) or {}
        # Robustly read last_processed_ts; ignore old string-format last_published
        last_processed_ts = extra.get("last_processed_ts", 0)
        if not isinstance(last_processed_ts, (int, float)):
            last_processed_ts = 0

        newest_ts = 0
        now_ts = datetime.now(timezone.utc).timestamp()
        cutoff_ts = now_ts - (MAX_AGE_DAYS * 86400)

        for entry in parsed.entries:
            link = entry.get("link", "")
            if not link or is_url_processed(link):
                continue

            entry_ts = _entry_timestamp(entry)
            entry_dt = datetime.fromtimestamp(entry_ts, tz=timezone.utc) if entry_ts else datetime.now(timezone.utc)
            date_iso = _format_iso_date(entry_dt)

            # On first run (no processed timestamp), only fetch last 24h to avoid backlog
            if not last_processed_ts:
                if entry_ts and (now_ts - entry_ts) > 86400:
                    continue

            # Date filtering: skip old articles
            if entry_ts and entry_ts < cutoff_ts:
                log_info(f"RSS {source_name}: skipping old article ({date_iso}): {link[:70]}")
                mark_url_processed(link, f"rss_{source_name}", "too_old")
                continue

            # Skip already-seen by timestamp comparison (allows same-day articles)
            if last_processed_ts and entry_ts and entry_ts < last_processed_ts:
                continue

            # Fetch full article text
            text = ""
            if entry.get("content"):
                text = entry.content[0].value
            elif entry.get("summary"):
                text = entry.summary
            else:
                try:
                    proxies = _build_proxy_dict() if use_proxy else {}
                    r = requests.get(link, timeout=20, headers={"User-Agent": RSS_USER_AGENT}, proxies=proxies)
                    text = r.text
                except Exception:
                    pass

            articles.append({
                "title": entry.get("title", ""),
                "url": link,
                "text": text,
                "date": date_iso,
                "source": f"rss_{source_name}",
            })
            mark_url_processed(link, f"rss_{source_name}", entry.get("title", ""))

            if entry_ts and entry_ts > newest_ts:
                newest_ts = entry_ts

            # Limit per cycle
            if len(articles) >= MAX_PER_SOURCE:
                log_info(f"RSS {source_name}: reached limit of {MAX_PER_SOURCE}")
                break

        if newest_ts:
            set_cron_state(f"rss_{source_name}", datetime.now(timezone.utc).isoformat(), {"last_processed_ts": newest_ts})

        log_info(f"RSS {source_name}: {len(articles)} new articles")
        return articles
    except Exception as e:
        log_error(f"RSS fetch error ({source_name}): {e}")
        return []


def execute() -> list[dict]:
    all_articles = []
    # Normal RSS
    for name, url in SOURCES.get("rss", {}).items():
        articles = fetch_feed(name, url)
        all_articles.extend(articles)
    # Proxy RSS (for blocked sources that require proxy)
    for name, url in SOURCES.get("rss_proxy", {}).items():
        articles = fetch_feed(name, url, use_proxy=True)
        all_articles.extend(articles)
    return all_articles


if __name__ == "__main__":
    result = execute()
    print(f"Fetched {len(result)} articles")
    for a in result[:3]:
        print(a["title"], a["url"], a["date"])
