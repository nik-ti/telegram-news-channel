# NMD News Channel Template

A reusable Telegram news channel automation template. Copy this directory, configure three files, and you have a new channel.

## What it does

- Fetches news from **RSS feeds** and **crawled websites**
- Runs an AI pipeline: summarize → relevance check → duplicate detection → post writing
- Sends posts to an **admin approval channel** with a single inline Approve button
- On approval, publishes to the **public channel**
- Posts not approved within **48 hours** are auto-archived (cleanup runs every 6h)
- Stores everything in **Notion** for tracking

## Architecture

```
Single Process (aiohttp + aiogram + APScheduler)
    │
    ├── Every N minutes → run_pipeline()
    │       ├── fetch_rss.py      → RSS feeds
    │       └── fetch_crawl.py    → Crawled websites
    │       ↓
    │   summarizer.py (Gemini Flash)
    │       ↓
    │   relevance_checker.py (Gemini Flash)
    │       ↓
    │   duplicate_control.py (Gemini Flash)
    │       ↓
    │   post_writer.py (Grok 4.1 Fast)
    │       ↓
    │   post_validator.py (regex-only)  ← catches LLM refusal messages, no API call
    │       ↓
    │   Notion row (Status = Sent for approval)
    │       ↓
    │   Telegram admin channel (inline keyboard)
    │
    └── aiogram webhook → approve handler
        (posts ignored for 48h are auto-archived by cleanup job)
```

## How to create a new channel

### 1. Copy the template

```bash
cp -r template_channel my_new_channel
cd my_new_channel
```

### 2. Configure `.env`

```bash
cp .env.example .env
# Edit .env with your actual values
```

| Variable | What it is | Where to get it |
|----------|-----------|-----------------|
| `TELEGRAM_BOT_TOKEN` | Your bot's token | [@BotFather](https://t.me/BotFather) |
| `ADMIN_CHANNEL_ID` | Private channel for approvals | Create a channel, add your bot as admin, get the ID |
| `MAIN_CHANNEL_ID` | Public channel for posts | Same process |
| `NOTION_API_KEY` | Notion integration token | Notion → Settings → Integrations |
| `NOTION_DATABASE_ID` | Your Notion DB ID | Copy from the URL |
| `OPENROUTER_API_KEY` | OpenRouter API key | [openrouter.ai](https://openrouter.ai) |
| `WEBHOOK_HOST` | Your domain + path | e.g. `https://yourdomain.com/news_webhook` |
| `WEBHOOK_PORT` | Local port | e.g. `8082` (must be unique per bot!) |
| `PROXY_SERVER` | Proxy IP (optional) | Your proxy provider |
| `PROXY_PORT` | Proxy port (optional) | Your proxy provider |
| `PROXY_USERNAME` | Proxy auth username (optional) | Your proxy provider |
| `PROXY_PASSWORD` | Proxy auth password (optional) | Your proxy provider |

**Important:** Each bot needs its own `WEBHOOK_PORT` if running on the same server. Use 8082, 8083, 8084, etc.

The proxy vars are optional — only needed if you have sources with `"use_proxy": True` in config or entries under `"rss_proxy"`. Use a **residential proxy** for Cloudflare-protected sites; datacenter IPs will still be blocked.

### 3. Configure `utils/config.py`

Edit the `SOURCES` dict to add your RSS feeds and crawl sources:

```python
SOURCES = {
    "rss": {
        "my_source": "https://example.com/feed.xml",
    },
    "rss_proxy": {
        # Same format as "rss" but fetched through the proxy
        "blocked_feed": "https://example.com/feed.xml",
    },
    "crawl": {
        "my_website": {
            "url": "https://example.com/news/",
            "base_url": "https://example.com",
            "href_filter": "/news/",
            # "href_regex": r"/news/\d+",   # optional extra filter
            # "listing_method": "post",      # default is "get"
            # "use_proxy": True,             # set True for Cloudflare-blocked sites
        },
    },
}
```

**Proxy support:** If a source is behind Cloudflare or otherwise blocks the VPS IP, add `"use_proxy": True` to its crawl config and set `PROXY_*` vars in `.env`. The proxy is used only for that source's browser session — the rest of the crawler runs direct. For RSS feeds, add them under `"rss_proxy"` instead of `"rss"`.

**Crawler anti-detection:** The crawler already runs with `enable_stealth`, `user_agent_mode="random"`, `magic=True`, `simulate_user=True`, and `override_navigator=True`. These reduce the bot fingerprint and handle common overlays. They help with basic bot detection but do **not** bypass Cloudflare JS challenge — that requires a residential proxy.

### 4. Configure `nodes/post_writer.py`

Edit the `SYSTEM_MESSAGE` to match your channel's topic and tone. Change:
- The topic description
- The examples
- The context requirements
- The emojis

Keep the **Core Rule** — "You MUST write the post. ALWAYS. NO EXCEPTIONS. Your output is ONLY the post itself." — this prevents the LLM from refusing.

### 5. Run it

```bash
# Install dependencies
pip install -r requirements.txt

# Run directly
python main.py

# Or with Docker
docker-compose up -d
```

## File overview

| File | Purpose | Do I need to edit it? |
|------|---------|----------------------|
| `.env` | Secrets and config | ✅ Yes — required |
| `utils/config.py` | Sources, channels, scheduling | ✅ Yes — required |
| `nodes/post_writer.py` | LLM prompt for writing posts | ✅ Yes — customize topic/tone |
| `main.py` | Orchestrator (webhook + scheduler) | ❌ No — usually fine as-is |
| `nodes/fetch_rss.py` | RSS fetching | ❌ No |
| `nodes/fetch_crawl.py` | Web crawling | ❌ No |
| `nodes/summarizer.py` | Article summarization | ❌ No |
| `nodes/relevance_checker.py` | Relevance filter | ❌ No |
| `nodes/duplicate_control.py` | Duplicate detection | ❌ No |
| `nodes/post_validator.py` | Regex-only refusal catcher (Russian phrases) | ❌ No |
| `utils/telegram_client.py` | Telegram publishing | ❌ No |
| `utils/notion_client.py` | Notion integration | ❌ No |
| `utils/openrouter.py` | LLM API client | ❌ No |
| `utils/state_db.py` | SQLite processed URLs | ❌ No |
| `utils/logger.py` | Logging | ❌ No |

## Tips for multiple channels on one server

1. **Unique ports:** Each bot needs a unique `WEBHOOK_PORT` (8082, 8083, 8084...)
2. **Unique webhooks:** Each bot needs a unique `WEBHOOK_PATH` (`/news_webhook`, `/re_webhook`, `/tech_webhook`...)
3. **Separate Notion DBs:** Use a different `NOTION_DATABASE_ID` per channel
4. **Same OpenRouter key:** One API key works for all bots

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| "Address already in use" | Port conflict | Change `WEBHOOK_PORT` in `.env` |
| "Can't parse entities" | LLM generated bad HTML | Already handled by `sanitize_telegram_html` |
| "Post writer returned empty" | LLM refused to write | Already handled by `post_validator` |
| RSS returns 0 articles | Feed is stale or blocked | Check feed URL; if blocked, move to `rss_proxy` |
| Crawl returns 0 links | Website blocks bots | Add `"use_proxy": True` to that source |
| "Cloudflare JS challenge" | Cloudflare bot protection | Requires residential proxy — datacenter IPs are always blocked |
| "407 Proxy Auth Required" | Wrong proxy credentials | Update `PROXY_*` vars in `.env` |
| "502 Bad Gateway" from proxy | Proxy IP is down/expired | Get new proxy credentials from your provider |

## Tech stack

- **Python 3.10+** with asyncio
- **aiogram** — Telegram bot framework
- **aiohttp** — Webhook server
- **APScheduler** — Cron-like job scheduling
- **crawl4ai** — Headless browser crawling
- **feedparser** — RSS parsing
- **OpenRouter** — LLM API gateway
- **Notion API** — Database/storage
- **SQLite** — Local URL deduplication
