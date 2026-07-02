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

import logging
import math
import time
from pathlib import Path

from google import genai
from google.genai import types

from . import config, delta

log = logging.getLogger(__name__)

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

# Polling cadence + safety ceiling for the async upload/index operation. Support
# articles are small and usually index in well under a second, so we start with a
# short interval (fast ops return almost immediately) and back off up to a ceiling
# so a genuinely slow op doesn't hammer the API. The timeout exists so a hung
# operation fails loudly instead of blocking the daily job forever.
INITIAL_POLL_INTERVAL_SECONDS = 0.5
POLL_INTERVAL_SECONDS = 3
WAIT_TIMEOUT_SECONDS = 300

# Per-request HTTP timeout for the genai client. WAIT_TIMEOUT_SECONDS only bounds
# the async index-polling loop; without this, a stalled upload/index HTTP call
# (a hung connection, proxy, or firewall) blocks the run forever instead of
# failing loudly. Expressed in milliseconds, as the SDK expects.
HTTP_TIMEOUT_SECONDS = 60


def get_client() -> genai.Client:
    """Return an authenticated Gemini client built from config.API_KEY."""
    config.require("API_KEY", config.API_KEY)
    return genai.Client(
        api_key=config.API_KEY,
        http_options=types.HttpOptions(timeout=HTTP_TIMEOUT_SECONDS * 1000),
    )


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
    log.warning(
        "Created File Search Store. Save this to .env as FILE_SEARCH_STORE_NAME "
        "to reuse it on the next run: FILE_SEARCH_STORE_NAME=%s",
        store.name,
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
    """Block until an upload/index operation finishes (it runs async).

    Raises TimeoutError if it does not finish within WAIT_TIMEOUT_SECONDS so a
    stuck operation surfaces as a failed run instead of hanging the daily job.
    """
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    interval = INITIAL_POLL_INTERVAL_SECONDS
    while not operation.done:
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"File Search operation did not finish within {WAIT_TIMEOUT_SECONDS}s"
            )
        time.sleep(interval)
        operation = client.operations.get(operation)
        interval = min(interval * 2, POLL_INTERVAL_SECONDS)
    return operation


def _documents_by_slug(client: genai.Client, store_name: str) -> dict[str, list[str]]:
    """Map each indexed document's slug (display_name) to its resource name(s).

    A slug can map to several names if a previous run left duplicates behind;
    upsert deletes all of them so the store self-heals.
    """
    mapping: dict[str, list[str]] = {}
    for doc in client.file_search_stores.documents.list(parent=store_name):
        mapping.setdefault(doc.display_name, []).append(doc.name)
    return mapping


def upload_files(
    client: genai.Client,
    store_name: str,
    paths: list[Path],
    *,
    replace: bool = True,
) -> int:
    """Upsert the given .md files into the File Search Store.

    Returns the (estimated) number of chunks embedded, for logging.

    With replace=True (default) every file's existing same-slug document(s) are
    deleted before the new version is indexed. This makes the operation
    idempotent — re-running never duplicates, and an "updated" article's stale
    version is removed instead of piling up alongside the new one (the Part 3
    concern the old NOTE deferred). Pass replace=False only for a store known to
    be empty (first-ever load) to skip the lookup.

    An operation that finishes in an error state raises, so a failed index is a
    failed run (state is not saved -> the file is retried next run) rather than a
    silent gap. Because upserts are idempotent, that retry is safe.
    """
    if not paths:
        return 0

    existing = _documents_by_slug(client, store_name) if replace else {}
    total_chunks = 0
    for path in paths:
        slug = path.stem  # human-readable doc key
        if replace:
            for name in existing.get(slug, []):
                # force=True: a document that already holds chunks is "non-empty",
                # and the API refuses to delete it without this flag.
                client.file_search_stores.documents.delete(
                    name=name, config={"force": True}
                )

        # Stamp the content hash onto the document so the next run can rebuild
        # the delta state straight from the store (see delta.load_state_from_store)
        # — no separate state file to persist or lose.
        text = path.read_text(encoding="utf-8")
        operation = client.file_search_stores.upload_to_file_search_store(
            file_search_store_name=store_name,
            file=str(path),
            config={
                "display_name": slug,
                # .md has no OS-level mimetype on Windows, so set it explicitly.
                "mime_type": "text/markdown",
                "chunking_config": CHUNKING_CONFIG,
                "custom_metadata": [
                    {
                        "key": delta.HASH_METADATA_KEY,
                        "string_value": delta.content_hash(text),
                    }
                ],
            },
        )
        operation = _wait(client, operation)
        if getattr(operation, "error", None):
            raise RuntimeError(f"indexing failed for {path.name}: {operation.error}")

        chunks = estimate_chunks(text)
        total_chunks += chunks
        log.info("indexed %s (~%d chunks)", path.name, chunks)
    return total_chunks


if __name__ == "__main__":
    config.setup_logging()
    files = sorted(config.ARTICLES_DIR.glob("*.md"))
    client = get_client()
    store_name = ensure_file_search_store(client)
    chunks = upload_files(client, store_name, files)
    log.info("uploaded %d files, ~%d chunks -> store %s", len(files), chunks, store_name)
