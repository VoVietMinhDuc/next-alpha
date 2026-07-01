"""Unit tests for src/scraper.py (Part 1: Zendesk API -> clean Markdown)."""

from __future__ import annotations

from pathlib import Path

import pytest
import requests
import responses

from src import scraper


# --------------------------------------------------------------------------- #
# slugify
# --------------------------------------------------------------------------- #
class TestSlugify:
    def test_basic_lowercase_and_dashes(self):
        assert scraper.slugify("How To Add a Video") == "how-to-add-a-video"

    def test_strips_unicode_accents(self):
        # NFKD normalize then drop non-ascii: é -> e
        assert scraper.slugify("Café Menu") == "cafe-menu"

    def test_removes_special_chars(self):
        assert scraper.slugify("What's new?! (2024)") == "whats-new-2024"

    def test_collapses_repeated_separators(self):
        assert scraper.slugify("a   b___c---d") == "a-b-c-d"

    def test_empty_falls_back_to_article(self):
        assert scraper.slugify("") == "article"
        # A title of only symbols also collapses to the fallback.
        assert scraper.slugify("!!! ???") == "article"


# --------------------------------------------------------------------------- #
# clean_html
# --------------------------------------------------------------------------- #
class TestCleanHtml:
    def test_removes_script_style_iframe_noscript(self):
        html = (
            "<p>keep me</p>"
            "<script>evil()</script>"
            "<style>.x{}</style>"
            "<iframe src='x'></iframe>"
            "<noscript>fallback</noscript>"
        )
        out = scraper.clean_html(html)
        assert "keep me" in out
        for gone in ("evil()", ".x{}", "<iframe", "fallback"):
            assert gone not in out

    def test_keeps_valid_content_and_links(self):
        html = "<h2>Title</h2><a href='/hc/articles/1'>link</a>"
        out = scraper.clean_html(html)
        assert "<h2>" in out
        assert "href" in out and "link" in out

    def test_handles_none_and_empty(self):
        assert scraper.clean_html(None) == ""
        assert scraper.clean_html("") == ""


# --------------------------------------------------------------------------- #
# html_to_markdown
# --------------------------------------------------------------------------- #
class TestHtmlToMarkdown:
    def test_contains_title_and_citation_header(self, sample_article):
        out = scraper.html_to_markdown(sample_article)
        assert out.startswith("# How to Add a YouTube Video")
        assert "Article URL: https://support.optisigns.com/hc/en-us/articles/12345" in out

    def test_strips_script_and_style_from_body(self, sample_article):
        out = scraper.html_to_markdown(sample_article)
        assert "tracker()" not in out
        assert "display:none" not in out

    def test_uses_atx_headings(self, sample_article):
        # "<h2>Getting Started</h2>" -> "## Getting Started", not underline style.
        out = scraper.html_to_markdown(sample_article)
        assert "## Getting Started" in out

    def test_preserves_body_links(self, sample_article):
        out = scraper.html_to_markdown(sample_article)
        assert "steps" in out
        assert "/hc/en-us/articles/999" in out

    def test_title_fallbacks(self):
        assert scraper.html_to_markdown({"name": "Fallback Name", "body": ""}).startswith(
            "# Fallback Name"
        )
        assert scraper.html_to_markdown({"body": ""}).startswith("# Untitled")

    def test_collapses_extra_blank_lines(self):
        article = {"title": "T", "html_url": "u", "body": "<p>a</p><br><br><br><p>b</p>"}
        out = scraper.html_to_markdown(article)
        assert "\n\n\n" not in out


# --------------------------------------------------------------------------- #
# save_markdown
# --------------------------------------------------------------------------- #
class TestSaveMarkdown:
    def test_writes_file_with_content(self, patch_articles_dir):
        path = scraper.save_markdown("my-slug", "# Hello\n")
        assert path == patch_articles_dir / "my-slug.md"
        assert path.read_text(encoding="utf-8") == "# Hello\n"

    def test_creates_directory_if_missing(self, patch_articles_dir):
        assert not patch_articles_dir.exists()
        scraper.save_markdown("s", "x")
        assert patch_articles_dir.is_dir()


# --------------------------------------------------------------------------- #
# fetch_articles (HTTP mocked with `responses`)
# --------------------------------------------------------------------------- #
def _article(idx: int, draft: bool = False) -> dict:
    return {
        "id": idx,
        "title": f"Article {idx}",
        "html_url": f"https://x/{idx}",
        "draft": draft,
        "body": f"<p>body {idx}</p>",
    }


class TestFetchArticles:
    @responses.activate
    def test_skips_drafts(self):
        responses.add(
            responses.GET,
            scraper.ARTICLES_URL,
            json={
                "articles": [_article(1), _article(2, draft=True), _article(3)],
                "meta": {"has_more": False},
                "links": {},
            },
            status=200,
        )
        got = scraper.fetch_articles()
        assert [a["id"] for a in got] == [1, 3]

    @responses.activate
    def test_respects_limit(self, monkeypatch):
        monkeypatch.setattr(scraper, "LIMIT", 2)
        responses.add(
            responses.GET,
            scraper.ARTICLES_URL,
            json={
                "articles": [_article(1), _article(2), _article(3), _article(4)],
                "meta": {"has_more": False},
                "links": {},
            },
            status=200,
        )
        got = scraper.fetch_articles()
        assert len(got) == 2
        assert [a["id"] for a in got] == [1, 2]

    @responses.activate
    def test_follows_cursor_pagination(self, monkeypatch):
        monkeypatch.setattr(scraper, "LIMIT", 100)  # don't cap; exercise pagination
        next_url = "https://support.optisigns.com/api/v2/help_center/en-us/articles?page[after]=abc"
        responses.add(
            responses.GET,
            scraper.ARTICLES_URL,
            json={
                "articles": [_article(1)],
                "meta": {"has_more": True},
                "links": {"next": next_url},
            },
            status=200,
        )
        responses.add(
            responses.GET,
            next_url,
            json={
                "articles": [_article(2)],
                "meta": {"has_more": False},
                "links": {},
            },
            status=200,
        )
        got = scraper.fetch_articles()
        assert [a["id"] for a in got] == [1, 2]

    @responses.activate
    def test_raises_on_http_error(self):
        responses.add(responses.GET, scraper.ARTICLES_URL, status=500)
        with pytest.raises(requests.HTTPError):
            scraper.fetch_articles()


# --------------------------------------------------------------------------- #
# scrape (orchestration; fetch mocked)
# --------------------------------------------------------------------------- #
class TestScrape:
    def test_writes_one_file_per_article(self, patch_articles_dir, mocker):
        articles = [
            {"id": 1, "title": "First Post", "html_url": "u1", "body": "<p>a</p>"},
            {"id": 2, "title": "Second Post", "html_url": "u2", "body": "<p>b</p>"},
        ]
        mocker.patch.object(scraper, "fetch_articles", return_value=articles)

        paths = scraper.scrape()

        assert all(isinstance(p, Path) for p in paths)
        assert {p.name for p in paths} == {"first-post-1.md", "second-post-2.md"}
        # slug = slugify(title)-id, and files actually exist on disk.
        assert all(p.exists() for p in paths)
