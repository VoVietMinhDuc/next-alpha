"""Delta detection — decide which articles are added / updated / skipped.

The vector store itself is the source of truth: each indexed document carries the
content hash of the version that was embedded (in its custom_metadata). On every
run we rebuild the previous {slug: hash} map straight from the store, so the job
is stateless — no local state file to lose. This works identically whether it
runs on an ephemeral container, a fresh VM, or locally.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# custom_metadata key under which each document stores the hash of its content.
HASH_METADATA_KEY = "content_hash"


def content_hash(text: str) -> str:
    """Stable SHA-256 hash of a file's content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_from_metadata(doc) -> str | None:
    """Pull the content_hash value out of a document's custom_metadata."""
    for meta in getattr(doc, "custom_metadata", None) or []:
        if meta.key == HASH_METADATA_KEY:
            return meta.string_value
    return None


def load_state_from_store(client, store_name: str) -> dict[str, str]:
    """Rebuild the {slug: hash} map from the store's documents (source of truth).

    Returns an empty map on the first run / an empty store. A document missing
    the hash metadata is skipped, so it re-uploads next run (self-healing).
    """
    state: dict[str, str] = {}
    for doc in client.file_search_stores.documents.list(parent=store_name):
        h = _hash_from_metadata(doc)
        if h:
            state[doc.display_name] = h
    return state


def diff(article_paths: list[Path], old_state: dict[str, str]) -> dict[str, list[Path]]:
    """Compare current files against the previous run's {slug: hash} map.

    Returns {"added": [...], "updated": [...], "skipped": [...]}.
    """
    added: list[Path] = []
    updated: list[Path] = []
    skipped: list[Path] = []

    for path in article_paths:
        slug = path.stem
        new_hash = content_hash(path.read_text(encoding="utf-8"))
        if slug not in old_state:
            added.append(path)
        elif old_state[slug] != new_hash:
            updated.append(path)
        else:
            skipped.append(path)

    return {"added": added, "updated": updated, "skipped": skipped}
