"""
NODE: Fetch Crawl
PURPOSE: Crawl non-RSS news sites using crawl4ai headless browser
INPUT: None
OUTPUT: List of article dicts {title, url, text, date, source}
DEPENDENCIES: crawl4ai, BeautifulSoup

NOTE: Uses crawl4ai for BOTH listing pages and article pages.
No requests fallback — the headless browser handles JS-rendered content
and is fast enough for our volume (a few pages per hour).
"""

import asyncio
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timezone, timedelta
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode, ProxyConfig
from utils.config import SOURCES, PROXY_SERVER, PROXY_PORT, PROXY_USERNAME, PROXY_PASSWORD
from utils.state_db import is_url_processed, mark_url_processed, get_cron_state, set_cron_state
from utils.logger import log_info, log_error

# ── Shared Crawler Instances (lazy-init, long-lived) ────────────────
_crawler: AsyncWebCrawler | None = None
_proxy_crawler: AsyncWebCrawler | None = None


def _browser_cfg(proxy_cfg=None) -> BrowserConfig:
    return BrowserConfig(
        headless=True,
        text_mode=True,
        light_mode=True,
        memory_saving_mode=True,
        verbose=False,
        enable_stealth=True,       # playwright-stealth to reduce bot fingerprint
        user_agent_mode="random",  # rotate UA on each browser start
        **({"proxy_config": proxy_cfg} if proxy_cfg else {}),
    )


async def _get_crawler() -> AsyncWebCrawler:
    """Return a started AsyncWebCrawler (direct connection)."""
    global _crawler
    if _crawler is None:
        _crawler = AsyncWebCrawler(config=_browser_cfg())
        await _crawler.start()
        log_info("Crawl4ai browser started")
    return _crawler


async def _get_proxy_crawler() -> AsyncWebCrawler:
    """Return a started AsyncWebCrawler that routes through the proxy.
    Only used for sources blocked from this VPS (requires proxy).
    """
    global _proxy_crawler
    if _proxy_crawler is None:
        proxy_cfg = ProxyConfig(
            server=f"http://{PROXY_SERVER}:{PROXY_PORT}",
            username=PROXY_USERNAME,
            password=PROXY_PASSWORD,
        )
        _proxy_crawler = AsyncWebCrawler(config=_browser_cfg(proxy_cfg))
        await _proxy_crawler.start()
        log_info("Crawl4ai proxy browser started")
    return _proxy_crawler


async def _close_crawlers():
    """Close all crawler instances and free memory. Call after each cycle."""
    global _crawler, _proxy_crawler
    if _crawler is not None:
        await _crawler.close()
        _crawler = None
        log_info("Crawl4ai browser closed")
    if _proxy_crawler is not None:
        await _proxy_crawler.close()
        _proxy_crawler = None
        log_info("Crawl4ai proxy browser closed")


# ── Config Constants ────────────────────────────────────────────────
# Non-article URL patterns to skip
SKIP_PATTERNS = [
    "/archive", "/index", "/page/", "/tag/", "/category/",
    ".pdf", ".jpg", ".png", ".zip", ".doc", ".xml",
    "#", "mailto:", "javascript:",
]

MAX_PER_SOURCE = 3       # max articles to process per source per cycle
MAX_AGE_DAYS = 2         # skip articles older than this 
LISTING_TIMEOUT = 30000  # 30s for listing pages
ARTICLE_TIMEOUT = 30000  # 30s for article pages

# Shared run config for listings (lightweight, just need HTML)
_LISTING_RUN_CFG = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,
    wait_until="domcontentloaded",
    page_timeout=LISTING_TIMEOUT,
    verbose=False,
    magic=True,            # auto-handle overlays/popups
    simulate_user=True,    # human-like mouse movements for anti-bot measures
    override_navigator=True,  # patch navigator properties to look like real browser
)

# Shared run config for articles (need full markdown)
_ARTICLE_RUN_CFG = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,
    wait_until="domcontentloaded",
    page_timeout=ARTICLE_TIMEOUT,
    verbose=False,
    magic=True,
    simulate_user=True,
    override_navigator=True,
)


# ── URL / Date Helpers ──────────────────────────────────────────────

def _should_skip_url(url: str) -> bool:
    lower = url.lower()
    return any(p in lower for p in SKIP_PATTERNS)


def _extract_date_from_url(url: str) -> str | None:
    """Extract YYYY-MM-DD from URL patterns like /2026/05/slug/."""
    m = re.search(r"/(\d{4})/(\d{2})/", url)
    if m:
        return f"{m.group(1)}-{m.group(2)}-01"
    m = re.search(r"/(\d{4})-(\d{2})-(\d{2})/", url)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _extract_date_from_html(html: str) -> str | None:
    """Try to extract publication date from article page HTML."""
    soup = BeautifulSoup(html, "lxml")

    # Meta tags
    for meta in soup.find_all("meta"):
        prop = meta.get("property", "").lower()
        name = meta.get("name", "").lower()
        if prop in ("article:published_time", "og:published_time") or name in ("publisheddate", "date", "pubdate"):
            content = meta.get("content", "")
            if content:
                m = re.match(r"(\d{4})-(\d{2})-(\d{2})", content)
                if m:
                    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # <time> tags
    for time_tag in soup.find_all("time"):
        dt = time_tag.get("datetime", "")
        if dt:
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})", dt)
            if m:
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # Common date classes
    for sel in [".date", ".published", ".pubdate", ".post-date", ".article-date", ".timestamp", ".cardDate"]:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
            if m:
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            m = re.search(
                r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
                text, re.I,
            )
            if m:
                months = {
                    "january": "01", "february": "02", "march": "03", "april": "04",
                    "may": "05", "june": "06", "july": "07", "august": "08",
                    "september": "09", "october": "10", "november": "11", "december": "12",
                }
                return f"{m.group(3)}-{months[m.group(1).lower()]}-{m.group(2).zfill(2)}"

    # Fallback: scan raw text for the first "Month DD, YYYY" occurrence
    raw_text = soup.get_text(separator=" ", strip=True)
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
        raw_text[:3000], re.I,
    )
    if m:
        months = {
            "january": "01", "february": "02", "march": "03", "april": "04",
            "may": "05", "june": "06", "july": "07", "august": "08",
            "september": "09", "october": "10", "november": "11", "december": "12",
        }
        return f"{m.group(3)}-{months[m.group(1).lower()]}-{m.group(2).zfill(2)}"

    return None


def _is_too_old(url: str, html: str = "", pre_extracted_date: str = "") -> bool:
    """Check if article is older than MAX_AGE_DAYS.
    
    Uses pre_extracted_date first (from raw HTML in _parse_article), then URL pattern,
    then falls back to scanning the provided text/HTML.
    """
    date_str = pre_extracted_date or _extract_date_from_url(url)
    if not date_str and html:
        date_str = _extract_date_from_html(html)

    if not date_str:
        return False  # can't determine → allow (conservative)

    try:
        article_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
        is_old = article_date < cutoff
        if is_old:
            log_info(f"Skipping old article ({date_str}): {url[:80]}")
        return is_old
    except Exception:
        return False


# ── Listing Page ────────────────────────────────────────────────────

def _parse_links_from_soup(soup: BeautifulSoup, listing_url: str, base_url: str, href_filter: str, href_regex: str = "") -> list[dict]:
    links = []
    seen = set()
    listing_path = listing_url.rstrip("/")

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if not href:
            continue

        full = urljoin(base_url or listing_url, href)
        full_clean = full.rstrip("/")

        if full_clean == listing_path:
            continue
        if href_filter and href_filter not in full:
            continue
        if href_regex and not re.search(href_regex, full):
            continue
        if _should_skip_url(full):
            continue
        if full in seen or ("#" in full and full.split("#")[0] in seen):
            continue

        seen.add(full)
        title = a.get_text(strip=True) or ""
        links.append({"url": full, "title": title})

    return links


async def _fetch_listing(listing_url: str, base_url: str, href_filter: str, href_regex: str = "", use_proxy: bool = False) -> list[dict]:
    """Crawl a listing page with crawl4ai and extract article links."""
    crawler = await _get_proxy_crawler() if use_proxy else await _get_crawler()
    try:
        result = await crawler.arun(url=listing_url, config=_LISTING_RUN_CFG)
        if not result.success:
            log_error(f"Listing crawl failed ({listing_url}): {result.error_message}")
            return []
        soup = BeautifulSoup(result.html, "lxml")
        return _parse_links_from_soup(soup, listing_url, base_url, href_filter, href_regex)
    except Exception as e:
        log_error(f"Listing crawl exception ({listing_url}): {e}")
        return []


# ── Article Pages ───────────────────────────────────────────────────

def _parse_article(result) -> dict | None:
    """Turn a CrawlResult into our article dict."""
    if not result.success:
        log_error(f"Article crawl failed ({result.url}): {result.error_message}")
        return None

    text = result.markdown or ""
    title = ""
    if result.metadata:
        title = result.metadata.get("title", "")

    if len(text) < 300:
        log_info(f"Article too short ({len(text)} chars), skipping: {result.url}")
        return None

    # Detect access-denied pages
    if "access denied" in text.lower() or "accessdenied" in title.lower():
        log_info(f"Access denied page detected, skipping: {result.url}")
        return None

    date_str = _extract_date_from_html(result.html) or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return {
        "title": title,
        "url": result.url,
        "text": text,
        "date": date_str,
        "source": "crawl",
    }


async def _fetch_articles_batch(urls: list[str], use_proxy: bool = False) -> list[dict]:
    """Fetch multiple articles in one batch using arun_many."""
    if not urls:
        return []

    crawler = await _get_proxy_crawler() if use_proxy else await _get_crawler()
    try:
        results = await crawler.arun_many(urls=urls, config=_ARTICLE_RUN_CFG)
        articles = []
        for result in results:
            article = _parse_article(result)
            if article:
                articles.append(article)
        return articles
    except Exception as e:
        log_error(f"Batch article crawl failed: {e}")
        return []


# ── Source Orchestrator ─────────────────────────────────────────────

async def fetch_source(source_key: str, config: dict) -> list[dict]:
    log_info(f"Crawling source: {source_key}")
    listing_url = config["url"]
    href_filter = config.get("href_filter", "")
    href_regex = config.get("href_regex", "")
    base_url = config.get("base_url", "")
    use_proxy = config.get("use_proxy", False)

    # 1. Crawl listing page
    links = await _fetch_listing(listing_url, base_url, href_filter, href_regex, use_proxy)
    if not links:
        log_info(f"{source_key}: no links found on listing page")
        set_cron_state(f"crawl_{source_key}", datetime.now(timezone.utc).isoformat())
        return []

    # 2. Filter already processed
    new_links = [l for l in links if not is_url_processed(l["url"])]

    # 3. Always limit to top N
    if len(new_links) > MAX_PER_SOURCE:
        new_links = new_links[:MAX_PER_SOURCE]
        log_info(f"{source_key}: limiting to top {MAX_PER_SOURCE} articles")

    log_info(f"{source_key}: {len(new_links)} new URLs out of {len(links)} total")

    if not new_links:
        set_cron_state(f"crawl_{source_key}", datetime.now(timezone.utc).isoformat())
        return []

    # 4. Batch-crawl all article pages
    urls = [l["url"] for l in new_links]
    link_titles = {l["url"]: l["title"] for l in new_links}

    raw_articles = await _fetch_articles_batch(urls, use_proxy)

    # 5. Post-process: date filtering, dedup, enrich
    articles = []
    for article in raw_articles:
        url = article["url"]

        # Date filter
        if _is_too_old(url, article.get("text", ""), article.get("date", "")):
            mark_url_processed(url, f"crawl_{source_key}", "too_old")
            continue

        article["source"] = f"crawl_{source_key}"
        if not article.get("title"):
            article["title"] = link_titles.get(url, "")

        articles.append(article)
        mark_url_processed(url, f"crawl_{source_key}", article["title"])

    set_cron_state(f"crawl_{source_key}", datetime.now(timezone.utc).isoformat())
    log_info(f"{source_key}: {len(articles)} articles ready for pipeline")
    return articles


# ── Public API ──────────────────────────────────────────────────────

async def execute() -> list[dict]:
    all_articles = []
    try:
        for key, cfg in SOURCES["crawl"].items():
            articles = await fetch_source(key, cfg)
            all_articles.extend(articles)
        return all_articles
    finally:
        await _close_crawlers()


def run():
    return asyncio.run(execute())


if __name__ == "__main__":
    arts = run()
    print(f"Fetched {len(arts)} articles")
    for a in arts[:3]:
        print(f"- {a['title'][:60]} | {a['url'][:70]} | date={a['date']} chars={len(a['text'])}")
