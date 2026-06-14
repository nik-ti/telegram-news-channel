"""
AI NODE: Relevance Checker
PURPOSE: Determine if article is relevant to your channel's topic
MODEL: google/gemini-2.5-flash
TEMPERATURE: 0.2

CUSTOMIZE THE SYSTEM_MESSAGE BELOW FOR YOUR CHANNEL'S TOPIC.
"""

from utils.openrouter import chat_completion
from utils.logger import log_info, log_error

MODEL = "google/gemini-2.5-flash"
TEMPERATURE = 0.2
MAX_TOKENS = 1000

# ═══════════════════════════════════════════════════════════════
# CUSTOMIZE THIS PROMPT FOR YOUR CHANNEL
# ═══════════════════════════════════════════════════════════════
# Change:
#   - The topic description
#   - The audience description
#   - The relevance rules
#
# KEEP:
#   - The JSON output format
#   - The single-variable JSON requirement
# ═══════════════════════════════════════════════════════════════

SYSTEM_MESSAGE = """Overview:
You are a relevance-classifier for a Telegram news channel. Your job is to decide whether an article should be posted or skipped.

Return only JSON:
{
  "is_relevant": true/false
}

Audience:
[DESCRIBE YOUR AUDIENCE HERE]

Task:
You will receive an article, and your job is to decide whether or not it is relevant to this news channel.

Rules:
- Article is considered relevant if [DEFINE RELEVANCE].
- Article is considered irrelevant if [DEFINE IRRELEVANCE].

Your entire output must be valid, single variable JSON with no additional text or symbols."""


def execute(article_text: str) -> bool:
    log_info("Relevance checker running...")
    try:
        result = chat_completion(
            prompt=f"Article: {article_text}",
            system_message=SYSTEM_MESSAGE,
            model=MODEL,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            json_mode=True,
        )
        is_relevant = result.get("is_relevant", False)
        log_info(f"Relevance: {is_relevant}")
        return bool(is_relevant)
    except Exception as e:
        log_error(f"Relevance checker error: {e}")
        return False
