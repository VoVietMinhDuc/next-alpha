"""Dev helper — inspect the Gemini File Search Store from the terminal.

File Search Stores created via API are not browsable in the AI Studio UI, so this
is the practical way to "see" what's indexed. Two modes:

    python -m src.inspect_store                 # store overview + document list
    python -m src.inspect_store "your question" # grounded query + citations

Requires FILE_SEARCH_STORE_NAME (and API_KEY) in the environment / .env.
"""

from __future__ import annotations

import sys
import time

from google.genai import types

from . import config
from .uploader import get_client

# Model used only for the optional grounded-query demo below.
QUERY_MODEL = "gemini-2.5-flash"


def _store_name() -> str:
    """Return the configured store name or fail fast with a clear message."""
    return config.require("FILE_SEARCH_STORE_NAME", config.FILE_SEARCH_STORE_NAME)


def show_overview(client, store_name: str) -> None:
    """Print store-level stats and every indexed document."""
    store = client.file_search_stores.get(name=store_name)
    print("=== STORE ===")
    print(f"name            : {store.name}")
    print(f"display_name    : {store.display_name}")
    print(f"active documents: {store.active_documents_count}")
    print(f"size_bytes      : {store.size_bytes}")
    print(f"embedding_model : {store.embedding_model}")
    print()

    print("=== DOCUMENTS ===")
    count = 0
    for doc in client.file_search_stores.documents.list(parent=store_name):
        count += 1
        state = getattr(doc, "state", None)
        size = getattr(doc, "size_bytes", None)
        print(f"{count:2}. {doc.display_name}")
        print(f"    state={state}  size={size}")
    print(f"\ntotal documents: {count}")


def run_query(client, store_name: str, question: str, retries: int = 4) -> None:
    """Ask a question grounded on the store and print the answer + citations.

    Gemini models occasionally return 503 (high demand); retry with a short
    backoff so a transient blip doesn't look like a real failure.
    """
    cfg = types.GenerateContentConfig(
        tools=[
            types.Tool(
                file_search=types.FileSearch(file_search_store_names=[store_name])
            )
        ]
    )

    resp = None
    for attempt in range(1, retries + 1):
        try:
            resp = client.models.generate_content(
                model=QUERY_MODEL, contents=question, config=cfg
            )
            break
        except Exception as exc:  # noqa: BLE001 - surface then retry transient errors
            print(f"attempt {attempt}/{retries} failed: {type(exc).__name__}: "
                  f"{str(exc)[:100]}")
            if attempt < retries:
                time.sleep(5)
    if resp is None:
        raise SystemExit("Query kept failing (model unavailable). Try again later.")

    print(f"Q: {question}\n")
    print("ANSWER:")
    print(resp.text)
    print("\n=== CITATIONS ===")
    metadata = getattr(resp.candidates[0], "grounding_metadata", None)
    chunks = getattr(metadata, "grounding_chunks", None) if metadata else None
    if not chunks:
        print("(no grounding chunks returned — answer may not be grounded)")
        return
    seen = set()
    for chunk in chunks:
        ctx = getattr(chunk, "retrieved_context", None)
        title = getattr(ctx, "title", None) if ctx else None
        if title and title not in seen:
            seen.add(title)
            print(f" - {title}")


if __name__ == "__main__":
    client = get_client()
    store_name = _store_name()

    question = " ".join(sys.argv[1:]).strip()
    if question:
        run_query(client, store_name, question)
    else:
        show_overview(client, store_name)
