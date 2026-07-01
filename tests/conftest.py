"""Shared fixtures for the test suite."""

from __future__ import annotations

import pytest

from src import config, scraper


@pytest.fixture
def sample_article() -> dict:
    """A minimal Zendesk-shaped article dict, like fetch_articles() returns."""
    return {
        "id": 12345,
        "title": "How to Add a YouTube Video",
        "html_url": "https://support.optisigns.com/hc/en-us/articles/12345-How-to-Add-a-YouTube-Video",
        "draft": False,
        "body": (
            "<h2>Getting Started</h2>"
            "<p>Follow these <a href='/hc/en-us/articles/999'>steps</a>.</p>"
            "<script>tracker();</script>"
            "<style>.ad{display:none}</style>"
        ),
    }


@pytest.fixture
def patch_articles_dir(tmp_path, monkeypatch):
    """Redirect config.ARTICLES_DIR to a temp dir so file writes never touch real data."""
    articles_dir = tmp_path / "articles"
    monkeypatch.setattr(config, "ARTICLES_DIR", articles_dir)
    # scraper.py imported `config` as a module, so patching the attribute is enough
    # (it reads config.ARTICLES_DIR at call time, not at import time).
    return articles_dir
