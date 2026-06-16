"""
MAIN WORKFLOW ORCHESTRATOR — Single Process
============================================

CUSTOMIZE THESE FOR YOUR CHANNEL:
  1. utils/config.py      → add your RSS feeds and crawl sources
  2. nodes/post_writer.py → edit the SYSTEM_MESSAGE for your topic/tone
  3. .env                 → add your bot tokens, channel IDs, Notion credentials
============================================
Runs the Telegram webhook server AND the article pipeline scheduler
in the SAME asyncio event loop. This eliminates:
  • SQLite race conditions between scheduler & webhook
  • Cross-process state sync issues
  • Button infinite-loading (handlers return in <1 sec, work is backgrounded)

Architecture:
  aiohttp App (webhook endpoint)
    ├── aiogram CallbackQuery handlers (approve/decline)
    │   └── Answer immediately → remove buttons → background task
    └── APScheduler (hourly article pipeline)
"""

import os
# The VPS has a global HTTP(S)_PROXY for trading scripts that breaks
# Playwright/Chromium (ERR_INVALID_AUTH_CREDENTIALS). Remove it for this process.
for _proxy_key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                     "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
    os.environ.pop(_proxy_key, None)

del _proxy_key, os

import asyncio
from datetime import datetime, timezone
from aiohttp import web
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import CallbackQuery
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from utils.config import (
    TELEGRAM_BOT_TOKEN, WEBHOOK_HOST, WEBHOOK_PATH, WEBHOOK_PORT,
    CRON_INTERVAL_MINUTES, ADMIN_CHANNEL_ID, MAIN_CHANNEL_ID,
)
from utils.logger import log_info, log_error
from utils.telegram_error import send_error
from utils.state_db import init_db, is_url_processed, mark_url_processed
from utils.notion_client import (
    url_exists, create_post, update_post_status, get_page_by_id,
    get_stale_pending_posts, archive_post,
)
from utils.telegram_client import get_bot, publish_post_text, sanitize_telegram_html

from nodes import fetch_rss, fetch_crawl
from nodes.summarizer import execute as summarize
from nodes.relevance_checker import execute as check_relevance
from nodes.duplicate_control import execute as check_duplicate
from nodes.post_writer import execute as write_post
from nodes.post_validator import execute as validate_post

# ── Dispatcher & Router (module level, shared by webhook + scheduler) ──
dp = Dispatcher()
router = Router()
dp.include_router(router)


# Catch-all update logger (for debugging)
@dp.update()
async def log_all_updates(update):
    update_type = type(update).__name__
    log_info(f"[WEBHOOK] Received update: {update_type} (id={update.update_id})")


# Error handler for dispatcher
@dp.error()
async def log_dispatcher_errors(event):
    log_error(f"[WEBHOOK] Handler error: {event.exception}")
    send_error(str(event.exception), node_name="webhook_handler")


# ──────────────────────────────────────────────────────────────
# APPROVAL CALLBACK HANDLERS
# ──────────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("approve:"))
async def approve_handler(query: CallbackQuery):
    """
    Handle Approve button press.
    Critical: answer immediately, remove buttons, then background the heavy work.
    This prevents infinite spinner / timeout.
    """
    page_id = query.data.split(":", 1)[1]
    log_info(f"[BUTTON] Approve clicked for page_id={page_id}")

    # 1. ACKNOWLEDGE IMMEDIATELY — stops the spinner
    #    Wrapped in try/except because if this fails, nothing else matters
    try:
        await query.answer("⏳ Публикуем...")
        log_info(f"[BUTTON] query.answer() succeeded for approve:{page_id}")
    except Exception as e:
        log_error(f"[BUTTON] query.answer() FAILED for approve:{page_id}: {e}")
        # Still try to process — the user will see a spinner but work continues

    # 2. Validate we can edit the message
    if not query.message:
        log_error(f"[BUTTON] query.message is None for approve:{page_id}")
        return

    # 3. Fetch page data from Notion (stateless — works after restarts)
    try:
        page_data = get_page_by_id(page_id)
        log_info(f"[BUTTON] Notion fetch succeeded for {page_id}")
    except Exception as e:
        log_error(f"[BUTTON] Notion fetch error for {page_id}: {e}")
        try:
            await query.message.edit_text("⚠️ Ошибка: не удалось загрузить данные из Notion")
        except Exception as e2:
            log_error(f"[BUTTON] Failed to edit message after Notion error: {e2}")
        return

    if not page_data:
        log_info(f"[BUTTON] page_data is None for {page_id}")
        try:
            await query.message.edit_text("⚠️ Пост не найден в Notion")
        except Exception as e:
            log_error(f"[BUTTON] Failed to edit message (not found): {e}")
        return

    # 4. DOUBLE-POST PROTECTION
    status = page_data.get("status", "")
    title = page_data.get("title", "Unknown")
    log_info(f"[BUTTON] Status={status}, Title={title}")

    if status == "Posted":
        try:
            await query.message.edit_text(f"✅ Уже опубликовано: {title}")
        except Exception as e:
            log_error(f"[BUTTON] Failed to edit message (already posted): {e}")
        return
    # 5. REMOVE KEYBOARD so button can't be clicked again
    try:
        await query.message.edit_reply_markup(reply_markup=None)
        log_info(f"[BUTTON] Keyboard removed for {page_id}")
    except Exception as e:
        log_error(f"[BUTTON] Failed to remove keyboard for {page_id}: {e}")

    # 6. Show "processing" state on the message
    try:
        await query.message.edit_text(
            "⏳ <b>Публикация...</b>",
            parse_mode="HTML",
        )
        log_info(f"[BUTTON] Processing message shown for {page_id}")
    except Exception as e:
        log_error(f"[BUTTON] Failed to show processing message for {page_id}: {e}")

    # 7. BACKGROUND TASK — all heavy work (posting, Notion update)
    # This returns immediately so Telegram never times out
    log_info(f"[BUTTON] Starting background approve task for {page_id}")
    asyncio.create_task(_background_approve(query, page_id, page_data))


async def _background_approve(query: CallbackQuery, page_id: str, page_data: dict):
    """Do the actual publishing work in the background."""
    title = page_data.get("title", "Unknown")
    post_text = page_data.get("post_text", "")

    try:
        if not post_text:
            log_error(f"[BUTTON] Empty post_text for {page_id}")
            await query.message.edit_text(
                f"⚠️ <b>Ошибка: пустой текст поста</b>\n{title}",
                parse_mode="HTML",
            )
            return

        # Publish to main channel
        log_info(f"[BUTTON] Publishing post for {page_id}")
        post_url = await publish_post_text(post_text)
        log_info(f"[BUTTON] Post published: {post_url}")

        # Update Notion
        update_post_status(page_id, "Posted", post_url)
        log_info(f"[BUTTON] Notion updated to Posted for {page_id}")

        # Final edit on admin message
        await query.message.edit_text(
            f"✅ <b>Опубликовано</b>\n\n{post_url}",
            parse_mode="HTML",
            disable_web_page_preview=False,
        )

        log_info(f"Approved & posted: {page_id} → {post_url}")

    except Exception as e:
        log_error(f"Background approve error: {e}")
        send_error(str(e), node_name="background_approve")
        try:
            await query.message.edit_text(
                f"⚠️ <b>Ошибка публикации</b>\n\n{e}",
                parse_mode="HTML",
            )
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────
# ARTICLE PIPELINE
# ──────────────────────────────────────────────────────────────


async def process_article(article: dict):
    """Process a single article through the entire pipeline."""
    try:
        url = article.get("url", "N/A")
        log_info(f"Processing: {url}")

        # 1. URL dedup via Notion
        if url_exists(url):
            log_info("URL already in Notion, skipping")
            mark_url_processed(url, article.get("source", "unknown"), article.get("title", ""))
            return

        # 2. Validate data
        text = article.get("text", "")
        if not text or not url:
            log_info("Missing text or url, skipping")
            return

        # 3. Summarize
        summary = summarize(text)
        if summary.get("article_text") == "SKIP" or summary.get("article_title") == "SKIP":
            log_info("Summarizer returned SKIP")
            return

        # 4. Relevance check
        is_relevant = check_relevance(summary["article_text"])
        if not is_relevant:
            log_info("Article not relevant, skipping")
            return

        # 5. Duplicate control
        is_dup = check_duplicate(summary["article_text"])
        if is_dup:
            log_info("Duplicate detected, skipping")
            return

        # 6. Write post
        post_text = write_post(summary["article_text"])
        if not post_text:
            log_error("Post writer returned empty")
            return

        # 6b. Validate post is not a refusal/rejection message
        is_valid = validate_post(post_text)
        if not is_valid:
            log_info("Post validator rejected output (LLM refusal message)")
            mark_url_processed(url, article.get("source", "unknown"), "rejected_by_post_writer")
            return

        # 7. Validate before Notion
        title = summary.get("article_title", "")
        if not title or not post_text:
            log_info("Empty title or post_text, skipping")
            return

        # 8. Create Notion row
        article_date = article.get("date", "")
        if "T" in article_date:
            article_date = article_date.split("T")[0]
        if not article_date:
            article_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        notion_page = create_post(
            title=title,
            post_text=post_text,
            source_url=url,
            article_date=article_date,
            summary=summary["article_text"],
            status="Sent for approval",
            post_type="News",
        )
        page_id = notion_page["id"]

        # 9. Send preview to admin channel
        bot = get_bot()
        safe_post = sanitize_telegram_html(post_text)
        caption = f"{safe_post}\n\n🔗 <a href='{url}'>Источник</a>"
        msg = await bot.send_message(
            chat_id=ADMIN_CHANNEL_ID,
            text=caption[:4096],
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        log_info(f"Preview sent (msg_id={msg.message_id})")

        # 10. Send approval button as a separate reply
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{page_id}"),
            ]
        ])
        await bot.send_message(
            chat_id=ADMIN_CHANNEL_ID,
            text="👆 <b>Опубликовать?</b>",
            parse_mode="HTML",
            reply_markup=keyboard,
            reply_to_message_id=msg.message_id,
        )

        log_info(f"Article queued for approval: {page_id}")

    except Exception as e:
        log_error(f"Pipeline error for {article.get('url')}: {e}")
        send_error(str(e), node_name="process_article")


async def cleanup_stale_posts():
    """Archive Notion posts that have been pending approval for more than 48 hours."""
    log_info("=== Stale post cleanup started ===")
    stale = get_stale_pending_posts(hours=48)
    log_info(f"Found {len(stale)} stale pending post(s)")
    for item in stale:
        archive_post(item["id"])
    log_info("=== Stale post cleanup complete ===")


async def run_pipeline():
    """One full cycle: fetch all sources, process each article."""
    log_info("=== Workflow cycle started ===")

    # Fetch RSS
    rss_articles = fetch_rss.execute()
    log_info(f"RSS articles: {len(rss_articles)}")

    # Fetch crawl
    crawl_articles = await fetch_crawl.execute()
    log_info(f"Crawl articles: {len(crawl_articles)}")

    all_articles = rss_articles + crawl_articles
    log_info(f"Total new articles: {len(all_articles)}")

    for article in all_articles:
        await process_article(article)

    log_info("=== Workflow cycle complete ===")


# ──────────────────────────────────────────────────────────────
# AIOHTTP APP (Webhook + Scheduler)
# ──────────────────────────────────────────────────────────────


async def on_startup(app: web.Application):
    """Set webhook, start dispatcher, and start scheduler when app boots."""
    bot = get_bot()

    # 1. EXPLICITLY start the dispatcher (critical for webhook handling)
    await dp.emit_startup(bot=bot)
    log_info("Dispatcher started")

    # 2. Set webhook
    webhook_url = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
    await bot.set_webhook(webhook_url)
    log_info(f"Webhook set: {webhook_url}")

    # 3. Start scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_pipeline,
        trigger="interval",
        minutes=CRON_INTERVAL_MINUTES,
        id="news_cycle",
        replace_existing=True,
    )
    scheduler.add_job(
        cleanup_stale_posts,
        trigger="interval",
        hours=6,
        id="stale_cleanup",
        replace_existing=True,
    )
    scheduler.start()
    log_info(f"Scheduler started (every {CRON_INTERVAL_MINUTES} min, cleanup every 6h)")

    # 4. Run pipeline immediately
    asyncio.create_task(run_pipeline())


async def on_shutdown(app: web.Application):
    """Clean shutdown."""
    bot = get_bot()
    await dp.emit_shutdown(bot=bot)
    log_info("Dispatcher shut down")


async def health(request):
    return web.Response(text="OK")


async def root(request):
    return web.Response(text="NMD News Bot is running")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/", root)

    # Register aiogram webhook handler on the module-level dispatcher
    SimpleRequestHandler(dispatcher=dp, bot=get_bot()).register(app, path=WEBHOOK_PATH)

    # Manual startup/shutdown (setup_application is unreliable here)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    init_db()
    app = create_app()
    web.run_app(app, host="127.0.0.1", port=WEBHOOK_PORT)
