"""
UTIL: Telegram Error Notifier
PURPOSE: Send error alerts to admin Telegram channel
"""

import asyncio
from aiogram import Bot
from utils.config import TELEGRAM_ERROR_BOT_TOKEN, TELEGRAM_ERROR_CHAT_ID
from utils.logger import log_error as _log_error

_bot: Bot | None = None


def _get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=TELEGRAM_ERROR_BOT_TOKEN)
    return _bot


async def _send_async(message: str, node_name: str):
    try:
        bot = _get_bot()
        text = f"🚨 <b>NMD News Bot Error</b>\n📍 Node: <code>{node_name}</code>\n❌ {message[:800]}"
        await bot.send_message(
            chat_id=TELEGRAM_ERROR_CHAT_ID,
            text=text,
            parse_mode="HTML",
        )
    except Exception as e:
        _log_error(f"Failed to send Telegram error: {e}")


def send_error(message: str, node_name: str = "Unknown"):
    """Send error notification to Telegram (fire-and-forget)."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_send_async(message, node_name))
    except RuntimeError:
        asyncio.run(_send_async(message, node_name))
