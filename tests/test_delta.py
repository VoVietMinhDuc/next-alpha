"""Unit tests for src/delta.py (change detection between daily runs).

Pure local logic + a mocked store listing — no network. The previous run's
{slug: hash} map is rebuilt from the store's documents (source of truth), so
these tests feed either a plain dict or a mocked documents.list.
"""

from __future__ import annotations

from src import delta


def _md(tmp_path, name, text="hello"):
    """Write a Markdown file named <name>.md and return its Path."""
    p = tmp_path / f"{name}.md"
    p.write_text(text, encoding="utf-8")
    return p


def _doc(mocker, slug, hash_value):
    """A mocked store Document carrying a content_hash in custom_metadata."""
    meta = mocker.MagicMock()
    meta.key = delta.HASH_METADATA_KEY
    meta.string_value = hash_value
    return mocker.MagicMock(display_name=slug, custom_metadata=[meta])


# --------------------------------------------------------------------------- #
# content_hash (pure)
# --------------------------------------------------------------------------- #
class TestContentHash:
    def test_is_stable_for_same_input(self):
        assert delta.content_hash("abc") == delta.content_hash("abc")

    def test_differs_for_different_input(self):
        assert delta.content_hash("abc") != delta.content_hash("abd")

    def test_is_sha256_hexdigest(self):
        # 64 hex chars = 256 bits.
        h = delta.content_hash("anything")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# --------------------------------------------------------------------------- #
# load_state_from_store (rebuild {slug: hash} from the store's documents)
# --------------------------------------------------------------------------- #
class TestLoadStateFromStore:
    def test_builds_map_from_documents(self, mocker):
        client = mocker.MagicMock()
        client.file_search_stores.documents.list.return_value = [
            _doc(mocker, "alpha", "h1"),
            _doc(mocker, "beta", "h2"),
        ]

        state = delta.load_state_from_store(client, "store")

        assert state == {"alpha": "h1", "beta": "h2"}
        client.file_search_stores.documents.list.assert_called_once_with(parent="store")

    def test_empty_store_is_empty_state(self, mocker):
        client = mocker.MagicMock()
        client.file_search_stores.documents.list.return_value = []
        assert delta.load_state_from_store(client, "store") == {}

    def test_document_without_hash_metadata_is_ignored(self, mocker):
        # A doc with no content_hash is skipped -> it re-uploads next run.
        client = mocker.MagicMock()
        no_meta = mocker.MagicMock(display_name="no-hash", custom_metadata=None)
        client.file_search_stores.documents.list.return_value = [
            no_meta,
            _doc(mocker, "alpha", "h1"),
        ]
        assert delta.load_state_from_store(client, "store") == {"alpha": "h1"}


# --------------------------------------------------------------------------- #
# diff (added / updated / skipped classification)
# --------------------------------------------------------------------------- #
class TestDiff:
    def test_all_new_files_are_added(self, tmp_path):
        a = _md(tmp_path, "alpha")
        b = _md(tmp_path, "beta")

        result = delta.diff([a, b], {})  # empty prior state = first run

        assert result["added"] == [a, b]
        assert result["updated"] == []
        assert result["skipped"] == []

    def test_unchanged_file_is_skipped(self, tmp_path):
        a = _md(tmp_path, "alpha", "same content")
        old = {"alpha": delta.content_hash("same content")}

        result = delta.diff([a], old)

        assert result["skipped"] == [a]
        assert result["added"] == []
        assert result["updated"] == []

    def test_modified_file_is_updated(self, tmp_path):
        a = _md(tmp_path, "alpha", "changed")
        old = {"alpha": delta.content_hash("original")}  # store has old hash

        result = delta.diff([a], old)

        assert result["updated"] == [a]
        assert result["added"] == []
        assert result["skipped"] == []

    def test_mixed_added_updated_skipped(self, tmp_path):
        unchanged = _md(tmp_path, "unchanged", "keep")
        modified = _md(tmp_path, "modified", "after")
        brand_new = _md(tmp_path, "brand_new", "fresh")
        old = {
            "unchanged": delta.content_hash("keep"),
            "modified": delta.content_hash("before"),  # differs from "after"
        }

        result = delta.diff([unchanged, modified, brand_new], old)

        assert result["added"] == [brand_new]
        assert result["updated"] == [modified]
        assert result["skipped"] == [unchanged]
