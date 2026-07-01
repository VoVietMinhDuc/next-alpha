"""OptiBot — ask the assistant a question, grounded on the File Search Store.

This is the "assistant" deliverable from the brief: it applies the OptiBot system
prompt (README -> "Assistant system prompt") on top of Gemini's File Search tool,
so the reply is answered *only* from the uploaded OptiSigns articles and cites the
"Article URL:" lines the scraper prepended to each doc. Use it to produce the
sample-answer screenshot the brief asks for.

    python -m src.ask                              # brief's sample question
    python -m src.ask "How do I add a YouTube video?"

Requires FILE_SEARCH_STORE_NAME (and API_KEY) in the environment / .env.
"""

from __future__ import annotations

import re
import sys
import time

from google.genai import types

from . import config
from .uploader import get_client

# Windows consoles default to cp1252; model output contains Unicode (arrows,
# bullets, curly quotes), so force UTF-8 to avoid UnicodeEncodeError on print.
sys.stdout.reconfigure(encoding="utf-8")

QUERY_MODEL = "gemini-2.5-flash"

# The brief's default demo question (used when no question is passed on the CLI).
DEFAULT_QUESTION = "How do I add a YouTube video?"

# Copied verbatim from README -> "Assistant system prompt" so the documented
# prompt and the running assistant never drift apart.
SYSTEM_INSTRUCTION = (
    "You are OptiBot, the customer-support bot for OptiSigns.com.\n"
    "• Tone: helpful, factual, concise.\n"
    "• Only answer using the uploaded docs.\n"
    "• Max 5 bullet points; else link to the doc.\n"
    '• Cite up to 3 "Article URL:" lines per reply.'
)


def ask(client, store_name: str, question: str, retries: int = 4):
    """Return the model response for a question, grounded on the store.

    Gemini models occasionally return 503 (high demand); retry with a short
    backoff so a transient blip doesn't look like a real failure.
    """
    cfg = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        tools=[
            types.Tool(
                file_search=types.FileSearch(file_search_store_names=[store_name])
            )
        ],
    )
    for attempt in range(1, retries + 1):
        try:
            return client.models.generate_content(
                model=QUERY_MODEL, contents=question, config=cfg
            )
        except Exception as exc:  # noqa: BLE001 - surface then retry transient errors
            print(f"attempt {attempt}/{retries} failed: {type(exc).__name__}: "
                  f"{str(exc)[:100]}")
            if attempt < retries:
                time.sleep(5)
    raise SystemExit("Query kept failing (model unavailable). Try again later.")


def cited_urls(resp) -> list[str]:
    """Pull the distinct "Article URL:" lines the model cited from the docs."""
    urls: list[str] = []
    for match in re.findall(r"Article URL:\s*(\S+)", resp.text or ""):
        if match not in urls:
            urls.append(match)
    return urls


if __name__ == "__main__":
    client = get_client()
    store_name = config.require(
        "FILE_SEARCH_STORE_NAME", config.FILE_SEARCH_STORE_NAME
    )
    question = " ".join(sys.argv[1:]).strip() or DEFAULT_QUESTION

    resp = ask(client, store_name, question)

    print(f"Q: {question}\n")
    print("OptiBot:")
    print(resp.text)

    urls = cited_urls(resp)
    if urls:
        print("\n=== Cited Article URLs ===")
        for url in urls:
            print(f" - {url}")
