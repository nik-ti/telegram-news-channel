"""
AI NODE: Duplicate Control
PURPOSE: Check if article is a duplicate of recent posts (last 3 days)
MODEL: google/gemini-2.5-flash
TEMPERATURE: 0.2
"""

from utils.openrouter import chat_completion
from utils.notion_client import get_recent_posts
from utils.logger import log_info, log_error

MODEL = "google/gemini-2.5-flash"
TEMPERATURE = 0.2
MAX_TOKENS = 2000

SYSTEM_MESSAGE_TEMPLATE = """You are a strict duplicate-detection agent.

DUPLICATE CRITERIA:
A post counts as a duplicate if:
* The article contains the same news, event, announcement, update, or product release even if wording is different.
* It is the same source article rewritten or summarized.
* It describes the same fact, launch, partnership, acquisition, update, feature, product, model, policy, or dataset.

RECENT POSTS:
{recent_posts}

NEW ARTICLE TO CHECK:
{new_article_text}

REQUIRED OUTPUT FORMAT — return ONLY this JSON object, nothing else:
{{
  "article": "paste the new article text here",
  "is_duplicate": true/false
}}"""


def execute(new_article_text: str) -> bool:
    log_info("Duplicate control running...")
    try:
        recent = get_recent_posts(days=3)
        if not recent:
            log_info("No recent posts to compare against")
            return False

        recent_formatted = "\n\n---\n".join(
            [f"Title: {r['title']}\nText: {r['post_text'][:500]}" for r in recent]
        )

        system = SYSTEM_MESSAGE_TEMPLATE.format(
            recent_posts=recent_formatted,
            new_article_text=new_article_text,
        )

        result = chat_completion(
            prompt=new_article_text,
            system_message=system,
            model=MODEL,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            json_mode=True,
        )
        is_duplicate = result.get("is_duplicate", False)
        log_info(f"Duplicate: {is_duplicate}")
        return bool(is_duplicate)
    except Exception as e:
        log_error(f"Duplicate control error: {e}")
        return False
