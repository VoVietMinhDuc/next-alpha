"""Part 2 — Upload Markdown files to a Gemini File Search Store via API (no UI drag-and-drop).

Gemini's File Search Tool is the Gemini equivalent of an OpenAI Vector Store: a
managed vector DB that auto-chunks, embeds, and cites source documents. We reuse
an existing store across runs (config.FILE_SEARCH_STORE_NAME); only the delta
files are uploaded. Run standalone for development:
    python -m src.uploader

Docs: https://ai.google.dev/gemini-api/docs/file-search
SDK:  https://github.com/googleapis/python-genai
"""

from __future__ import annotations

import math
import time
from pathlib import Path

from google import genai

from . import config

# Display name for the store we create on first run (only used to label it).
STORE_DISPLAY_NAME = "optibot-articles"

# Explicit chunking strategy (documented in README): article bodies are short
# support docs, so a modest chunk size with meaningful overlap keeps each chunk
# self-contained (won't split a step-by-step list mid-way) without ballooning
# embedding count. Gemini File Search caps max_tokens_per_chunk at 512.
MAX_TOKENS_PER_CHUNK = 500
MAX_OVERLAP_TOKENS = 100
CHUNKING_CONFIG = {
    "white_space_config": {
        "max_tokens_per_chunk": MAX_TOKENS_PER_CHUNK,
        "max_overlap_tokens": MAX_OVERLAP_TOKENS,
    }
}

# ~4 characters per token is the usual rough heuristic for English text. The
# File Search API does not report an exact per-file chunk count at upload time,
# so we estimate it from file length + the chunking config (see estimate_chunks).
CHARS_PER_TOKEN = 4


def get_client() -> genai.Client:
    """Return an authenticated Gemini client built from config.API_KEY."""
    config.require("API_KEY", config.API_KEY)
    return genai.Client(api_key=config.API_KEY)


def ensure_file_search_store(client: genai.Client) -> str:
    """Return the File Search Store resource name, creating one on first run.

    Reuse (config.FILE_SEARCH_STORE_NAME set) keeps the same store across daily
    runs so we never re-embed everything. First run creates a store and prints
    its name so it can be pasted into .env.
    """
    if config.FILE_SEARCH_STORE_NAME:
        # Confirm the configured store still exists; fail fast with a clear
        # message if it was deleted out from under us.
        store = client.file_search_stores.get(name=config.FILE_SEARCH_STORE_NAME)
        return store.name

    store = client.file_search_stores.create(
        config={"display_name": STORE_DISPLAY_NAME}
    )
    print(
        "Created File Search Store. Save this to .env as FILE_SEARCH_STORE_NAME "
        f"to reuse it on the next run:\n    FILE_SEARCH_STORE_NAME={store.name}"
    )
    return store.name


def estimate_chunks(text: str) -> int:
    """Rough chunk count for one file, consistent with CHUNKING_CONFIG.

    Chunks advance by (chunk size - overlap) tokens each step, so the effective
    stride is what determines how many chunks a document produces.
    """
    tokens = len(text) / CHARS_PER_TOKEN
    stride = MAX_TOKENS_PER_CHUNK - MAX_OVERLAP_TOKENS
    return max(1, math.ceil(tokens / stride)) # max (1, ceil(1000/400)) = 3 chunks


def _wait(client: genai.Client, operation):
    """Block until an upload/import operation finishes."""

    # wait until the operation is done (upload file is async)
    while not operation.done:
        time.sleep(3)
        operation = client.operations.get(operation)
    return operation


def upload_files(client: genai.Client, store_name: str, paths: list[Path]) -> int:
    """Upload + index the given .md files into the File Search Store.

    Returns the (estimated) number of chunks embedded, for logging.

    NOTE: this uploads unconditionally. Delta detection (only upload changed
    files) lives in Part 3 / delta.py; deleting a slug's previous document before
    re-uploading an "updated" article is a Part 3 concern and not handled here.
    """
    total_chunks = 0
    for path in paths:
        operation = client.file_search_stores.upload_to_file_search_store(
            file_search_store_name=store_name,
            file=str(path),
            config={
                "display_name": path.stem,  # slug, human-readable doc key
                # .md has no OS-level mimetype on Windows, so set it explicitly.
                "mime_type": "text/markdown",
                "chunking_config": CHUNKING_CONFIG,
            },
        )
        operation = _wait(client, operation)
        chunks = estimate_chunks(path.read_text(encoding="utf-8"))
        total_chunks += chunks
        print(f"  indexed {path.name}  (~{chunks} chunks)")
    return total_chunks


if __name__ == "__main__":
    files = sorted(config.ARTICLES_DIR.glob("*.md"))
    client = get_client()
    store_name = ensure_file_search_store(client)
    chunks = upload_files(client, store_name, files)
    print(f"Uploaded {len(files)} files, ~{chunks} chunks -> store {store_name}")
