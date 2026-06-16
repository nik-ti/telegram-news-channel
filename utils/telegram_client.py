"""
UTIL: Telegram Client
PURPOSE: Publish approved text-only posts to the main channel.
"""

import re
from aiogram import Bot
from utils.config import TELEGRAM_BOT_TOKEN, MAIN_CHANNEL_ID, ADMIN_CHANNEL_ID, SAFE_MODE
from utils.logger import log_info, log_error

_bot: Bot | None = None

# Telegram HTML parse_mode allows only these tags
_TELEGRAM_ALLOWED_TAGS = {
    "b", "i", "u", "s", "strike", "spoiler", "code", "pre", "a", "br", "em", "strong",
}


def sanitize_telegram_html(text: str) -> str:
    """Escape <...> sequences that aren't valid Telegram HTML tags.
    Prevents errors like 'Unsupported start tag "6%"' when article text
    contains raw characters like '<6%'.
    """
    def _replacer(m: re.Match) -> str:
        inner = m.group(1).strip().lower()
        # closing tag: </b>, </i>, etc.
        if inner.startswith("/"):
            tag = inner[1:].split()[0].split("=")[0]
            if tag in _TELEGRAM_ALLOWED_TAGS:
                return m.group(0)
        # opening/self-closing tag: <b>, <a href="...">, <br>, etc.
        tag = inner.split()[0].split("=")[0]
        if tag in _TELEGRAM_ALLOWED_TAGS:
            return m.group(0)
        # not an allowed tag — escape the brackets
        return m.group(0).replace("<", "&lt;").replace(">", "&gt;")

    return re.sub(r"<([^>]+)>", _replacer, text)


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=TELEGRAM_BOT_TOKEN)
    return _bot


async def _send_message_safe(bot: Bot, chat_id: str, text: str, **kwargs) -> object:
    """Send message with HTML parse_mode, falling back to plain text on parse error."""
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text[:4096],
            parse_mode="HTML",
            **kwargs,
        )
    except Exception as e:
        err_str = str(e).lower()
        if "can't parse entities" in err_str or "unexpected end tag" in err_str or "unsupported start tag" in err_str:
            log_error(f"HTML parse error, falling back to plain text: {e}")
            # Strip all HTML tags for fallback
            plain = re.sub(r"<[^>]+>", "", text)
            return await bot.send_message(
                chat_id=chat_id,
                text=plain[:4096],
                **kwargs,
            )
        raise


async def publish_post_with_image(post_text: str, file_id: str) -> str:
    """Publish a post with an image to the main channel. Returns Telegram post URL."""
    bot = get_bot()
    target = ADMIN_CHANNEL_ID if SAFE_MODE else MAIN_CHANNEL_ID
    target_name = "ADMIN (SAFE MODE)" if SAFE_MODE else MAIN_CHANNEL_ID

    try:
        msg = await bot.send_photo(
            chat_id=target,
            photo=file_id,
            caption=sanitize_telegram_html(post_text)[:1024],
            parse_mode="HTML",
        )

        url_base = MAIN_CHANNEL_ID if not SAFE_MODE else ADMIN_CHANNEL_ID
        if url_base.startswith("@"):
            post_url = f"https://t.me/{url_base.lstrip('@')}/{msg.message_id}"
        else:
            cid = url_base.replace("-100", "")
            post_url = f"https://t.me/c/{cid}/{msg.message_id}"

        log_info(f"Published post with image to {target_name}: {post_url}")
        return post_url

    except Exception as e:
        log_error(f"Failed to publish post with image: {e}")
        raise


async def publish_post_text(post_text: str) -> str:
    """Publish a text-only post to the main channel. Returns Telegram post URL."""
    bot = get_bot()
    target = ADMIN_CHANNEL_ID if SAFE_MODE else MAIN_CHANNEL_ID
    target_name = "ADMIN (SAFE MODE)" if SAFE_MODE else MAIN_CHANNEL_ID

    safe_text = sanitize_telegram_html(post_text)

    try:
        msg = await _send_message_safe(
            bot,
            chat_id=target,
            text=safe_text,
            disable_web_page_preview=True,
        )

        # Build Telegram URL
        url_base = MAIN_CHANNEL_ID if not SAFE_MODE else ADMIN_CHANNEL_ID
        if url_base.startswith("@"):
            post_url = f"https://t.me/{url_base.lstrip('@')}/{msg.message_id}"
        else:
            cid = url_base.replace("-100", "")
            post_url = f"https://t.me/c/{cid}/{msg.message_id}"

        log_info(f"Published post to {target_name}: {post_url}")
        return post_url

    except Exception as e:
        log_error(f"Failed to publish post: {e}")
        raise
