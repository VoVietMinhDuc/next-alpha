"""Unit tests for src/uploader.py (Part 2: create/reuse store, upload via API).

All Gemini API calls are mocked — these tests never touch the network, so they
verify our logic (branching, config passed to the SDK, chunk accounting) rather
than the SDK itself.
"""

from __future__ import annotations

import math

import pytest

from src import config, delta, uploader


# --------------------------------------------------------------------------- #
# estimate_chunks (pure math)
# --------------------------------------------------------------------------- #
class TestEstimateChunks:
    def test_empty_text_is_at_least_one_chunk(self):
        assert uploader.estimate_chunks("") == 1

    def test_short_text_fits_in_one_chunk(self):
        # Well under one stride (stride = 400 tokens = 1600 chars).
        assert uploader.estimate_chunks("x" * 100) == 1

    def test_matches_stride_formula(self):
        # stride tokens = MAX_TOKENS_PER_CHUNK - MAX_OVERLAP_TOKENS
        stride = uploader.MAX_TOKENS_PER_CHUNK - uploader.MAX_OVERLAP_TOKENS
        text = "y" * 8000
        expected = math.ceil((len(text) / uploader.CHARS_PER_TOKEN) / stride)
        assert uploader.estimate_chunks(text) == expected
        assert expected > 1  # sanity: this input really is multi-chunk

    def test_boundary_rounds_up(self):
        # One char past an exact stride boundary must roll into a second chunk.
        stride_chars = (
            uploader.MAX_TOKENS_PER_CHUNK - uploader.MAX_OVERLAP_TOKENS
        ) * uploader.CHARS_PER_TOKEN
        assert uploader.estimate_chunks("z" * stride_chars) == 1
        assert uploader.estimate_chunks("z" * (stride_chars + 1)) == 2


# --------------------------------------------------------------------------- #
# get_client
# --------------------------------------------------------------------------- #
class TestGetClient:
    def test_raises_when_api_key_missing(self, monkeypatch):
        monkeypatch.setattr(config, "API_KEY", None)
        with pytest.raises(RuntimeError, match="API_KEY"):
            uploader.get_client()

    def test_builds_client_from_api_key(self, monkeypatch, mocker):
        monkeypatch.setattr(config, "API_KEY", "secret-key")
        fake_client_cls = mocker.patch("src.uploader.genai.Client")

        client = uploader.get_client()

        fake_client_cls.assert_called_once()
        kwargs = fake_client_cls.call_args.kwargs
        assert kwargs["api_key"] == "secret-key"
        # An explicit HTTP timeout is set so a stalled request fails loudly.
        assert kwargs["http_options"].timeout == uploader.HTTP_TIMEOUT_SECONDS * 1000
        assert client is fake_client_cls.return_value


# --------------------------------------------------------------------------- #
# ensure_file_search_store (reuse vs. create branches)
# --------------------------------------------------------------------------- #
class TestEnsureFileSearchStore:
    def test_reuses_configured_store(self, monkeypatch, mocker):
        monkeypatch.setattr(config, "FILE_SEARCH_STORE_NAME", "fileSearchStores/abc")
        client = mocker.MagicMock()
        client.file_search_stores.get.return_value.name = "fileSearchStores/abc"

        name = uploader.ensure_file_search_store(client)

        assert name == "fileSearchStores/abc"
        client.file_search_stores.get.assert_called_once_with(
            name="fileSearchStores/abc"
        )
        client.file_search_stores.create.assert_not_called()

    def test_creates_store_when_none_configured(self, monkeypatch, mocker, caplog):
        monkeypatch.setattr(config, "FILE_SEARCH_STORE_NAME", None)
        client = mocker.MagicMock()
        client.file_search_stores.create.return_value.name = "fileSearchStores/new"

        with caplog.at_level("WARNING", logger="src.uploader"):
            name = uploader.ensure_file_search_store(client)

        assert name == "fileSearchStores/new"
        client.file_search_stores.create.assert_called_once_with(
            config={"display_name": uploader.STORE_DISPLAY_NAME}
        )
        client.file_search_stores.get.assert_not_called()
        # Logs the new name so it can be saved to .env for reuse.
        assert "FILE_SEARCH_STORE_NAME=fileSearchStores/new" in caplog.text


# --------------------------------------------------------------------------- #
# _wait (poll until operation.done)
# --------------------------------------------------------------------------- #
class TestWait:
    def test_polls_until_done(self, mocker):
        mocker.patch("src.uploader.time.sleep")  # no real delay
        pending = mocker.MagicMock(done=False)
        finished = mocker.MagicMock(done=True)
        client = mocker.MagicMock()
        client.operations.get.return_value = finished

        result = uploader._wait(client, pending)

        assert result is finished
        client.operations.get.assert_called_once_with(pending)

    def test_returns_immediately_when_already_done(self, mocker):
        sleep = mocker.patch("src.uploader.time.sleep")
        finished = mocker.MagicMock(done=True)
        client = mocker.MagicMock()

        result = uploader._wait(client, finished)

        assert result is finished
        client.operations.get.assert_not_called()
        sleep.assert_not_called()

    def test_raises_when_operation_hangs_past_timeout(self, mocker):
        mocker.patch("src.uploader.time.sleep")
        # First monotonic() call sets the deadline; the next is past it.
        mocker.patch(
            "src.uploader.time.monotonic",
            side_effect=[0, uploader.WAIT_TIMEOUT_SECONDS + 1],
        )
        pending = mocker.MagicMock(done=False)
        client = mocker.MagicMock()

        with pytest.raises(TimeoutError):
            uploader._wait(client, pending)


# --------------------------------------------------------------------------- #
# upload_files (orchestration; SDK mocked)
# --------------------------------------------------------------------------- #
class TestUploadFiles:
    def test_empty_input_uploads_nothing(self, mocker):
        client = mocker.MagicMock()
        assert uploader.upload_files(client, "store", []) == 0
        client.file_search_stores.upload_to_file_search_store.assert_not_called()

    def test_uploads_each_file_with_expected_config(self, tmp_path, mocker):
        mocker.patch("src.uploader.time.sleep")
        a = tmp_path / "alpha.md"
        b = tmp_path / "beta.md"
        a.write_text("hello", encoding="utf-8")
        b.write_text("world", encoding="utf-8")

        client = mocker.MagicMock()
        client.file_search_stores.documents.list.return_value = []  # empty store
        op = client.file_search_stores.upload_to_file_search_store.return_value
        op.done = True
        op.error = None

        total = uploader.upload_files(client, "fileSearchStores/s", [a, b])

        upload = client.file_search_stores.upload_to_file_search_store
        assert upload.call_count == 2

        # Inspect the first call's keyword arguments.
        kwargs = upload.call_args_list[0].kwargs
        assert kwargs["file_search_store_name"] == "fileSearchStores/s"
        assert kwargs["file"] == str(a)
        assert kwargs["config"]["display_name"] == "alpha"  # path.stem = slug
        assert kwargs["config"]["mime_type"] == "text/markdown"
        assert kwargs["config"]["chunking_config"] is uploader.CHUNKING_CONFIG
        # Content hash is stamped on the doc so delta state lives in the store.
        meta = kwargs["config"]["custom_metadata"][0]
        assert meta["key"] == delta.HASH_METADATA_KEY
        assert meta["string_value"] == delta.content_hash("hello")

    def test_returns_sum_of_estimated_chunks(self, tmp_path, mocker):
        mocker.patch("src.uploader.time.sleep")
        files = []
        for i, size in enumerate((5, 4000, 9000)):
            p = tmp_path / f"doc{i}.md"
            p.write_text("q" * size, encoding="utf-8")
            files.append(p)

        client = mocker.MagicMock()
        client.file_search_stores.documents.list.return_value = []
        op = client.file_search_stores.upload_to_file_search_store.return_value
        op.done = True
        op.error = None

        total = uploader.upload_files(client, "store", files)

        expected = sum(uploader.estimate_chunks("q" * s) for s in (5, 4000, 9000))
        assert total == expected


class TestUploadFilesUpsert:
    """Delete-before-upload (idempotent upsert) + failure handling."""

    def _md(self, tmp_path, name, text="hello"):
        p = tmp_path / f"{name}.md"
        p.write_text(text, encoding="utf-8")
        return p

    def test_deletes_existing_same_slug_docs_before_upload(self, tmp_path, mocker):
        mocker.patch("src.uploader.time.sleep")
        alpha = self._md(tmp_path, "alpha")

        # Store already holds two stale "alpha" docs plus an unrelated "beta".
        # NOTE: `name` is reserved in the Mock constructor, so set it afterwards.
        stale1 = mocker.MagicMock(display_name="alpha")
        stale1.name = "documents/1"
        stale2 = mocker.MagicMock(display_name="alpha")
        stale2.name = "documents/2"
        beta = mocker.MagicMock(display_name="beta")
        beta.name = "documents/3"

        client = mocker.MagicMock()
        client.file_search_stores.documents.list.return_value = [stale1, stale2, beta]
        op = client.file_search_stores.upload_to_file_search_store.return_value
        op.done = True
        op.error = None

        uploader.upload_files(client, "store", [alpha])

        delete_calls = client.file_search_stores.documents.delete.call_args_list
        deleted = {c.kwargs["name"] for c in delete_calls}
        assert deleted == {"documents/1", "documents/2"}  # beta left untouched
        # force=True is required to delete a document that already holds chunks.
        assert all(c.kwargs["config"]["force"] is True for c in delete_calls)

    def test_replace_false_skips_lookup_and_delete(self, tmp_path, mocker):
        mocker.patch("src.uploader.time.sleep")
        alpha = self._md(tmp_path, "alpha")

        client = mocker.MagicMock()
        op = client.file_search_stores.upload_to_file_search_store.return_value
        op.done = True
        op.error = None

        uploader.upload_files(client, "store", [alpha], replace=False)

        client.file_search_stores.documents.list.assert_not_called()
        client.file_search_stores.documents.delete.assert_not_called()

    def test_raises_when_indexing_finishes_with_error(self, tmp_path, mocker):
        mocker.patch("src.uploader.time.sleep")
        alpha = self._md(tmp_path, "alpha")

        client = mocker.MagicMock()
        client.file_search_stores.documents.list.return_value = []
        op = client.file_search_stores.upload_to_file_search_store.return_value
        op.done = True
        op.error = "quota exceeded"

        with pytest.raises(RuntimeError, match="indexing failed"):
            uploader.upload_files(client, "store", [alpha])
