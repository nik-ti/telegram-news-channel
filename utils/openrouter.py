"""
UTIL: OpenRouter Client
PURPOSE: Structured LLM calls via OpenRouter with JSON mode and retries
"""

import json
import time
import requests
from utils.config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
from utils.logger import log_info, log_error, log_debug

MAX_RETRIES = 3
RETRY_DELAY = 5


def chat_completion(
    prompt: str,
    system_message: str,
    model: str,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    json_mode: bool = True,
) -> dict | str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://nmd-consulting.com",
        "X-Title": "NMD News Channel",
    }

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if json_mode:
        body["response_format"] = {"type": "json_object"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log_debug(f"OpenRouter → {model} (attempt {attempt})")
            resp = requests.post(
                OPENROUTER_BASE_URL,
                headers=headers,
                json=body,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            if json_mode:
                cleaned = content.strip()
                if cleaned.startswith("```"):
                    first_newline = cleaned.index("\n")
                    cleaned = cleaned[first_newline + 1 :]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
                # Try to extract JSON object if there's extra text
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    import re
                    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
                    if match:
                        return json.loads(match.group(0))
                    raise

            return content

        except requests.exceptions.HTTPError as e:
            log_error(f"OpenRouter HTTP error (attempt {attempt}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
            else:
                raise
        except json.JSONDecodeError as e:
            log_error(f"JSON parse error from {model}: {e}\nRaw: {content[:500]}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                raise
        except Exception as e:
            log_error(f"OpenRouter error (attempt {attempt}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
            else:
                raise
