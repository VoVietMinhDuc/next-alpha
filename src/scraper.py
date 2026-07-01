"""Part 1 — Scrape OptiSigns support articles via Zendesk API and save as clean Markdown.

The Zendesk Help Center API returns each article's body as HTML (no nav/ads — that
is page chrome the API already strips). We follow cursor pagination to pull every
published article (drafts are skipped), convert that HTML to Markdown, prepend a
title + "Article URL:" header (used for citations in Part 2), and write <slug>-<id>.md.

Run standalone for development:
    python -m src.scraper
"""

# not evaluated at runtime, but useful for IDEs and type checkers
from __future__ import annotations

import logging # structured run output instead of bare print
import re # used for slugify and collapsing blank lines
import unicodedata # solve unicode issues in slugify
from pathlib import Path

import requests # http

from bs4 import BeautifulSoup # html parsing

from markdownify import markdownify as md # html -> markdown

from . import config

log = logging.getLogger(__name__)

# Zendesk Help Center articles endpoint for the en-us locale.
ARTICLES_URL = f"{config.ZENDESK_BASE_URL}/en-us/articles"
PAGE_SIZE = 100
REQUEST_TIMEOUT = 30


def fetch_articles() -> list[dict]:
    """Pull all published articles from the Zendesk API, following cursor pagination.

    Returns a list of raw article dicts (id, title, body HTML, html_url, ...).
    """

    # Use a session to persist headers and connection pooling.
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})

    
    # MAX_ARTICLES <= 0 means "no cap": pull every published article.
    limit = config.MAX_ARTICLES if config.MAX_ARTICLES > 0 else None

    articles: list[dict] = []
    url: str | None = ARTICLES_URL
    params: dict | None = {"page[size]": PAGE_SIZE}

    while url:
        # FETCH: GET /api/v2/help_center/en-us/articles.json?page[size]=100
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        # Raise an exception for any non-2xx response (e.g., 401, 403, 404, 500).
        response.raise_for_status()
        #print(response.text)
        payload = response.json() #parse to dict

        for article in payload.get("articles", []):
            if article.get("draft"):
                continue  # skip unpublished drafts
            articles.append(article)
            # Stop as soon as we hit the configured cap (if any).
            if limit is not None and len(articles) >= limit:
                return articles[:limit]

        # Cursor pagination: links.next already carries the page[after] cursor.
        meta = payload.get("meta", {})
        url = payload.get("links", {}).get("next") if meta.get("has_more") else None
        params = None  # the cursor URL is fully-formed; don't re-send params

    return articles


def clean_html(body_html: str) -> str:
    """Drop any stray script/style/iframe nodes before conversion (defensive)."""
    # body_html is text
    # print(repr(body_html[:200])) 
    # print("cleaning html")
    soup = BeautifulSoup(body_html or "", "html.parser") # parse to a tree html
    # print(soup)
    for tag in soup(["script", "style", "iframe", "noscript"]):
        tag.decompose()
    return str(soup) #parse back to string for markdownify


def html_to_markdown(article: dict) -> str:
    """Convert one article's HTML body to clean Markdown with a citation header."""

    title = article.get("title") or article.get("name") or "Untitled"
    url = article.get("html_url", "")

    body_md = md(
        clean_html(article.get("body", "")),
        heading_style="ATX",        # use # headings
        bullets="-",                # consistent bullet char
        strip=["script", "style"],
    ).strip() # omit leading/trailing whitespace

    # Collapse 3+ blank lines that markdownify sometimes leaves behind.
    body_md = re.sub(r"\n{3,}", "\n\n", body_md) # replace with 1 blank line

    return f"# {title}\n\nArticle URL: {url}\n\n---\n\n{body_md}\n"


def slugify(title: str) -> str:
    """Turn a title into a filesystem-safe slug (ascii, lowercase, dash-separated)."""

    #café -> cafe` -> cafe (byte to str)
    #normalize to NFKD form, encode to ASCII bytes ignoring non-ASCII, then decode back to str
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()

    # Collapse whitespace and dashes, remove non-word chars, lowercase, and replace spaces with dashes.
    text = re.sub(r"[^\w\s-]", "", text).strip().lower() #\w not word char, \s whitespace, - dash
    text = re.sub(r"[\s_-]+", "-", text) #find more than 1 whitespace/dash/underscore and replace with single dash
    return text or "article" 


def save_markdown(slug: str, markdown: str) -> Path:
    """Write Markdown to data/articles/<slug>.md and return the path."""
    config.ARTICLES_DIR.mkdir(parents=True, exist_ok=True) #create directory if not exists
    path = config.ARTICLES_DIR / f"{slug}.md"
    path.write_text(markdown, encoding="utf-8") # write markdown to file
    return path


def scrape() -> list[Path]:
    """Full scrape pass: fetch -> convert -> save. Returns written file paths."""
    articles = fetch_articles()
    paths: list[Path] = []
    for article in articles:
        # Append id to keep filenames unique and stable across runs (good for delta).
        slug = f"{slugify(article.get('title', ''))}-{article['id']}" #id must exist (KeyError if not), title may be empty 
        markdown = html_to_markdown(article)
        paths.append(save_markdown(slug, markdown))
    return paths


if __name__ == "__main__": #run only if this file is executed directly (not imported)
    config.setup_logging()
    written = scrape()
    log.info("scraped %d articles -> %s", len(written), config.ARTICLES_DIR)
