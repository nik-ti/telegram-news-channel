"""
UTIL: Image Generator (Optional Add-on)
PURPOSE: Generate an image for a post via OpenAI gpt-image-2.
         Returns raw image bytes, or None on failure.

ENABLING:
  1. Set IMAGE_GENERATION_ENABLED=true in .env
  2. Set OPENAI_API_KEY in .env
"""

import base64
import aiohttp
from utils.config import OPENAI_API_KEY
from utils.logger import log_info, log_error

IMAGE_STYLE_GUIDELINES = """ОБЩИЙ СТИЛЬ:
Премиальный, современный, чистый, "дорогой" визуал для недвижимости/новостей/риэлторского бренда. Не мультяшный, не перегруженный. Ближе к luxury real estate / business news cover: фотореалистичная основа, аккуратная типографика, минимум текста, визуально дорого и профессионально.
ЦВЕТОВАЯ ПАЛИТРА:
Твои фирменные цвета: глубокий тёмно-синий/графитовый #293641 + золотисто-бежевый #ccae7c.
Любишь спокойные премиальные оттенки: тёмный фон, белый текст, золотые акценты.
Не любишь слишком яркие, кричащие, кислотные цвета.
КОМПОЗИЦИЯ:
Формат должен сразу подходить под Instagram/Facebook, без обрезания важных частей.
Текст — крупный, читаемый, обычно сверху или по центру, но так, чтобы не перекрывать главный объект.
Визуал должен быть сбалансирован: крупный главный объект + свободное место под текст.
Для Reels/Instagram важно оставлять безопасные поля, чтобы текст не обрезался сверху/слева.
ТЕКСТ:
Минимум текста. Лучше 2–5 слов, чем длинные абзацы.
Текст крупный, жирный, на русском, часто капсом.
Стиль: новостной, цепляющий, но не дешёвый.
Примеры: "ЗАМОРОЗКУ USCIS ОТМЕНИЛИ" / "НОВАЯ ПОЖАРНАЯ СТАНЦИЯ" / "HUD МЕНЯЕТ ПРАВИЛА"
Нужен хороший контраст: белый/золотой текст на тёмном фоне. Можно лёгкая тень или затемнение под текстом, но без грязных плашек.
ЭЛЕМЕНТЫ И ДЕТАЛИ:
Допустимы аккуратные иконки по теме: дом, здание, пожарная машина, суд, документы, город, инвестиции.
Можно использовать лёгкие геометрические линии, рамки, золотые акценты, мягкий градиент.
Нельзя перегружать деталями. Всё должно выглядеть как обложка бизнес-медиа, а не как рекламный баннер из Canva.
ОСВЕЩЕНИЕ И АТМОСФЕРА:
Любишь "дорогой" свет: мягкий вечерний, закатный, тёплый, cinematic, с глубиной.
Для недвижимости — можно чуть улучшать траву, освещение, делать дом более презентабельным, но не менять полностью реальность.
Атмосфера: уверенность, статус, профессиональность, luxury.
ЧТО НИКОГДА НЕ НАДО:
Не делать дешёвый дизайн. Не делать слишком много текста. Не делать мелкий нечитаемый текст. Не менять лица людей. Не обрезать важные части. Не использовать случайные шрифты и цвета. Не делать мультяшно, детско, слишком ярко или хаотично.
ЧТО ВСЕГДА НАДО:
Делать премиально, чисто, современно. Сохранять фирменную эстетику: тёмный графит/синий + золото/беж + белый. Крупный русский заголовок. Минимум текста. Хороший контраст. Правильный формат под Instagram/Facebook без обрезки.
ФОРМУЛА СТИЛЯ:
Премиальная минималистичная обложка в стиле luxury real estate/business news: тёмный графитовый фон, золотые акценты, крупный русский заголовок, минимум текста, фотореалистичный дорогой визуал, без перегруза и без обрезки под Instagram/Facebook."""

OPENAI_IMAGE_URL = "https://api.openai.com/v1/images/generations"


async def generate_image(post_text: str) -> bytes | None:
    """Call OpenAI gpt-image-2 and return raw image bytes, or None on failure."""
    if not OPENAI_API_KEY:
        log_error("[ImageGen] OPENAI_API_KEY not set")
        return None
    if not IMAGE_STYLE_GUIDELINES:
        log_error("[ImageGen] IMAGE_STYLE_GUIDELINES not configured")
        return None

    prompt = f"Generate a cover for a telegram news channel post.\n\n{IMAGE_STYLE_GUIDELINES}\n\nPost: {post_text}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                OPENAI_IMAGE_URL,
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": "gpt-image-2",
                    "prompt": prompt,
                    "n": 1,
                    "size": "1024x1024",
                },
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                b64_data = data["data"][0]["b64_json"]
                log_info("[ImageGen] Image generated successfully")
                return base64.b64decode(b64_data)

    except Exception as e:
        log_error(f"[ImageGen] Generation failed: {e}")
        return None
