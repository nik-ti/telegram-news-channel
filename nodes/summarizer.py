"""
AI NODE: Summarizer
PURPOSE: Extract main news event from full article text, trim to <1500 chars
MODEL: google/gemini-2.5-flash
TEMPERATURE: 0.3
"""

from utils.openrouter import chat_completion
from utils.logger import log_info, log_error

MODEL = "google/gemini-2.5-flash"
TEMPERATURE = 0.3
MAX_TOKENS = 4000

SYSTEM_MESSAGE = """You are an expert article processor. You will receive an entire article text, and your job is to read through it and find the main news event or key point it discusses. Then extract and return only the relevant content about that main event, trimming away any unrelated news, parsing artifacts, tags, advertisements, or other extraneous content.

Your entire summary output MUST be below 1500 characters long.

Rules:
* Your entire output must be 1,500 characters or less. If the relevant content exceeds this limit, trim it down to fit within 1,500 characters while preserving the main news event. THIS IS A HARD LIMIT. ARTICLE TEXT MUST BE LESS THAN 1500 CHARACTERS - REWRITE IF IT IS BIGGER.
* Retain the article's original structure and writing style so it's clear whether this is a news event, blog post, feature discussion, tutorial, or other content type.
* Remove any unrelated content, secondary stories, ads, navigation elements, or parsing artifacts.
* Preserve the original wording from the article for the parts you keep.
* Do not include external URLs unless they are specifically mentioned in the context of the main story (not random navigation or ad links). If a URL is directly related to the news event being discussed, include it.

Output format:
{
  "article_title": "YOUR OUTPUT",
  "article_text": "YOUR OUTPUT"
}

IMPORTANT: article_text must be below 1,500 characters long. If its bigger - rewrite.

* If the article is empty or does not contain any specific news event, you must set article_title and article_text to 'SKIP'.

Important: Only output the JSON object above. No other comments, explanations, or words. Your entire output must be valid JSON."""


def execute(article_text: str) -> dict:
    log_info("Summarizer running...")
    try:
        result = chat_completion(
            prompt=f"Full article text: {article_text}",
            system_message=SYSTEM_MESSAGE,
            model=MODEL,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            json_mode=True,
        )
        title = result.get("article_title", "")
        text = result.get("article_text", "")
        if title == "SKIP" or text == "SKIP":
            log_info("Summarizer returned SKIP")
            return {"article_title": "SKIP", "article_text": "SKIP"}
        log_info(f"Summarized: {title[:80]}...")
        return {"article_title": title, "article_text": text}
    except Exception as e:
        log_error(f"Summarizer error: {e}")
        return {"article_title": "SKIP", "article_text": "SKIP"}
