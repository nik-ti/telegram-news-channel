"""
AI NODE: Post Validator
PURPOSE: Catch obvious LLM refusal/rejection messages before they reach the admin channel.
MODEL: google/gemini-2.5-flash
TEMPERATURE: 0.0

This is a fail-safe. It should be VERY permissive — only reject clear refusal messages.
A bad post is still a post. Only reject if it's not a post at all.
"""

from utils.openrouter import chat_completion
from utils.logger import log_info, log_error

MODEL = "google/gemini-2.5-flash"
TEMPERATURE = 0.0
MAX_TOKENS = 100

_SYSTEM_MESSAGE = """You are a binary classifier. Your job is simple:

Is the text below a real news post, or a refusal/rejection message?

Return ONLY JSON:
{"is_valid_post": true}
or
{"is_valid_post": false}

TRUE = any real news post (even short, poorly written, off-topic, or weird).
FALSE = clear refusal language like "I'm sorry", "I cannot", "не относится", "следуя вашим инструкциям", "unfortunately", "not relevant", etc.
FALSE = completely empty text.
TRUE = everything else."""


def execute(post_text: str) -> bool:
    """Return True if post_text looks like a real post, False if it's a refusal message."""
    if not post_text:
        log_info("Post validator: empty text")
        return False

    # Fast-path: Russian refusal phrases (posts are always in Russian)
    lower = post_text.lower()
    refusal_phrases = [
        "не относится", "не связана", "не связан", "не по теме",
        "не имеет отношения", "не касается",
        "следуя вашим инструкциям", "следуя инструкциям",
        "согласно вашим инструкциям", "согласно инструкциям",
        "косвенно связан", "косвенно связана",
        "косвенное отношение", "косвенно затрагивает",
        "однако", "тем не менее", "все же",
        "призму", "глобального", "общего контекста",
        "в рамках", "в контексте", "на основании",
        "не могу написать", "не смогу написать",
        "отказываюсь", "вынужден отказаться",
        "данная статья", "эта статья", "статья не",
        "пост не", "не представляется возможным",
        "не содержит", "не нашел", "не нашёл",
        "не удалось", "не удается", "не удаётся",
    ]
    for phrase in refusal_phrases:
        if phrase in lower:
            log_info(f"Post validator: detected refusal phrase '{phrase}'")
            return False

    # Detect meta-commentary preamble
    lines = post_text.strip().split("\n")
    first_line = lines[0].strip().lower() if lines else ""
    if first_line.startswith(("эта статья", "this article", "данная статья", "the article")):
        log_info("Post validator: detected meta-commentary preamble")
        return False

    # API fallback disabled — fast-path regex is sufficient for Russian-only posts.
    # If refusal patterns evolve, uncomment below:
    #
    # try:
    #     result = chat_completion(
    #         prompt=f"Classify this text:\n\n{post_text[:1500]}",
    #         system_message=_SYSTEM_MESSAGE,
    #         model=MODEL,
    #         temperature=TEMPERATURE,
    #         max_tokens=MAX_TOKENS,
    #         json_mode=True,
    #     )
    #     is_valid = result.get("is_valid_post", False)
    #     log_info(f"Post validator API result: {is_valid}")
    #     return bool(is_valid)
    # except Exception as e:
    #     log_error(f"Post validator API error: {e}")
    #     return True

    return True
