"""Part 3 — Daily job entry point: scrape -> detect delta -> upload only changes.

Runs ONCE and exits 0 (one-shot). The daily repetition is handled by an external
scheduler (cron / platform scheduler), not by a loop inside this process.

    docker run -e API_KEY=... <image>   # runs this file, then exits
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from src import config, delta, scraper, uploader

log = logging.getLogger(__name__)


def log_run(summary: dict) -> None:
    """Log a one-line run summary and persist a machine-readable artefact.

    The artefact under logs/ stays pure JSON (no log prefix) so it can be parsed
    later; the emitted log line carries the same data through the standard
    logging channel with a timestamp/level for humans watching the run.
    """
    line = json.dumps(summary, ensure_ascii=False)
    log.info("run complete: %s", line)
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = summary["finished_at"].replace(":", "").replace("-", "")
    (config.LOGS_DIR / f"run-{stamp}.json").write_text(line, encoding="utf-8")


def run() -> int:
    started = datetime.now(timezone.utc).isoformat()

    # 1. Scrape -> Markdown
    article_paths = scraper.scrape()

    # 2. Connect to the store (which is also our source of truth for prior state).
    client = uploader.get_client()
    store_name = uploader.ensure_file_search_store(client)

    # 3. Detect delta against the hashes stored on the store's own documents.
    #    No local state file -> the job is stateless and survives ephemeral
    #    containers / fresh VMs without re-uploading everything.
    old_state = delta.load_state_from_store(client, store_name)
    changes = delta.diff(article_paths, old_state)
    to_upload = changes["added"] + changes["updated"]
    log.info(
        "delta: %d added, %d updated, %d skipped (of %d scraped)",
        len(changes["added"]),
        len(changes["updated"]),
        len(changes["skipped"]),
        len(article_paths),
    )

    # 4. Upload only the delta. upload_files upserts by slug and stamps the new
    #    content hash onto each document, so a successful upload IS the state
    #    update — an "updated" article replaces its old doc, and a failed/retried
    #    run is safe because upserts are idempotent. If the upload raises, the
    #    store's hashes stay unchanged -> the delta is re-detected next run.
    chunks_est = 0
    if to_upload:
        chunks_est = uploader.upload_files(client, store_name, to_upload)
    else:
        log.info("no changes to upload; store already up to date")

    # 5. Log counts. File counts are exact. The chunk count is an ESTIMATE — the
    #    Gemini File Search API does not report actual per-document chunk counts (a
    #    Document exposes only size_bytes/state), so it is derived from the chunking
    #    config. We also record the store's own API-reported totals (document count
    #    and byte size) as provider-sourced ground truth for "how much is embedded".
    store = client.file_search_stores.get(name=store_name)
    log_run(
        {
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "total": len(article_paths),
            "added": len(changes["added"]),
            "updated": len(changes["updated"]),
            "skipped": len(changes["skipped"]),
            "chunks_embedded_est": chunks_est,
            "documents_in_store": getattr(store, "active_documents_count", None),
            "store_size_bytes": getattr(store, "size_bytes", None),
        }
    )
    return 0


if __name__ == "__main__":
    config.setup_logging()
    sys.exit(run())
