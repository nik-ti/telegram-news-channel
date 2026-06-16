"""
UTIL: Config
PURPOSE: Centralized configuration loaded from .env
"""

import os
from dotenv import load_dotenv

load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY", "")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHANNEL_ID = os.getenv("ADMIN_CHANNEL_ID", "")
MAIN_CHANNEL_ID = os.getenv("MAIN_CHANNEL_ID", "")
TELEGRAM_ERROR_BOT_TOKEN = os.getenv("TELEGRAM_ERROR_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
TELEGRAM_ERROR_CHAT_ID = os.getenv("TELEGRAM_ERROR_CHAT_ID", ADMIN_CHANNEL_ID)
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/news_webhook")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8082"))
CRON_INTERVAL_MINUTES = int(os.getenv("CRON_INTERVAL_MINUTES", "60"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DATA_DIR = os.getenv("DATA_DIR", "./data")
SAFE_MODE = os.getenv("SAFE_MODE", "false").lower() == "true"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
IMAGE_GENERATION_ENABLED = os.getenv("IMAGE_GENERATION_ENABLED", "false").lower() == "true"

# Proxy config for blocked sources
PROXY_SERVER = os.getenv("PROXY_SERVER", "")
PROXY_PORT = os.getenv("PROXY_PORT", "")
PROXY_USERNAME = os.getenv("PROXY_USERNAME", "")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD", "")

# ═══════════════════════════════════════════════════════════════
# CUSTOMIZE THESE SOURCES FOR YOUR CHANNEL
# ═══════════════════════════════════════════════════════════════

SOURCES = {
    "rss": {
        # Add RSS feeds here. Format: "source_name": "feed_url"
        # Example:
        # "bal": "https://www.bal.com/feed/?post_type=bal_news",
        # "hrw": "https://www.hrw.org/rss/news",
    },
    "rss_proxy": {
        # RSS feeds that need a proxy (optional)
        # These routes through the proxy configured in .env
        # Example:
        # "uscis_forms": "https://www.uscis.gov/forms/forms-updates/rss-feed",
    },
    "crawl": {
        # Add websites to crawl here.
        # Format: "source_name": {url, base_url, href_filter, ...}
        #
        # Required:
        #   url: the listing page URL
        #   base_url: used to resolve relative links
        #   href_filter: only follow links containing this string
        #
        # Optional:
        #   href_regex: additional regex filter for links
        #   use_proxy: True if this source needs proxy
        #   listing_method: "get" (default) or "post"
        #
        # Example:
        # "travel_state": {
        #     "url": "https://travel.state.gov/content/travel/en/News/visas-news.html",
        #     "base_url": "https://travel.state.gov",
        #     "href_filter": "/News/visas-news/",
        # },
        # "amnesty": {
        #     "url": "https://www.amnesty.org/en/latest/news/",
        #     "base_url": "https://www.amnesty.org",
        #     "href_filter": "/latest/news/",
        # },
    },
}
