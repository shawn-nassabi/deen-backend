"""
DEE-67 batch MT script tests.

Deterministic unit tests (mocked, no network/DB) for scripts/translate_references.py:
CLI parsing, translate_text(), _get_translation_client() key isolation, dry-run safety
(never calls Anthropic/DB), --limit sampling, and upsert_translation()'s idempotent
merge/commit shape.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest

from core.utils import compress_text
from scripts.translate_references import (
    DEFAULT_MODEL,
    DISABLED_REF_TYPES,
    SUPPORTED_LANGUAGES,
    _get_translation_client,
    _resolve_enabled_ref_types,
    parse_args,
    run_batch,
    translate_text,
    upsert_translation,
)


# ================================================================
# parse_args
# ================================================================

class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.languages == ",".join(SUPPORTED_LANGUAGES)
        assert args.ref_type == "all"
        assert args.dry_run is False
        assert args.model == DEFAULT_MODEL
        assert args.limit is None


# ================================================================
# _resolve_enabled_ref_types (DEE-67 follow-up: Quran MT hold-out)
# ================================================================

class TestResolveEnabledRefTypes:
    def test_all_excludes_quran_translation(self):
        assert _resolve_enabled_ref_types("all") == ["hadith", "tafsir_text"]

    def test_quran_translation_alone_yields_empty_list(self):
        assert _resolve_enabled_ref_types("quran_translation") == []

    def test_single_enabled_ref_type_passthrough(self):
        assert _resolve_enabled_ref_types("hadith") == ["hadith"]
        assert _resolve_enabled_ref_types("tafsir_text") == ["tafsir_text"]

    def test_disabled_ref_types_contains_quran_translation(self):
        assert DISABLED_REF_TYPES == {"quran_translation"}

    def test_disabled_ref_type_logs_warning(self, caplog):
        with caplog.at_level("WARNING"):
            _resolve_enabled_ref_types("quran_translation")

        assert "quran_translation" in caplog.text.lower()


# ================================================================
# _get_translation_client
# ================================================================

class TestGetTranslationClient:
    def test_raises_when_env_var_unset(self, monkeypatch):
        monkeypatch.delenv("TRANSLATION_ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError, match="TRANSLATION_ANTHROPIC_API_KEY"):
            _get_translation_client()

    def test_constructs_client_with_dedicated_key(self, monkeypatch):
        monkeypatch.setenv("TRANSLATION_ANTHROPIC_API_KEY", "sk-ant-personal-test-key")
        with patch("scripts.translate_references.Anthropic") as mocked_anthropic_cls:
            mocked_anthropic_cls.return_value = MagicMock()
            client = _get_translation_client()

        mocked_anthropic_cls.assert_called_once_with(api_key="sk-ant-personal-test-key")
        assert client is mocked_anthropic_cls.return_value


# ================================================================
# translate_text
# ================================================================

class TestTranslateText:
    def test_calls_messages_create_and_returns_stripped_text(self):
        fake_client = MagicMock()
        fake_client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(text="  translated output  ")]
        )

        result = translate_text(
            fake_client, model="claude-sonnet-5", text="source text", language="urdu"
        )

        assert result == "translated output"
        fake_client.messages.create.assert_called_once()
        _, kwargs = fake_client.messages.create.call_args
        assert kwargs["model"] == "claude-sonnet-5"
        assert "urdu" in kwargs["system"]
        assert kwargs["messages"] == [{"role": "user", "content": "source text"}]
        assert kwargs["max_tokens"] > 0


# ================================================================
# upsert_translation
# ================================================================

class _FakeSession:
    def __init__(self, recorder: dict):
        self._recorder = recorder

    def merge(self, row):
        self._recorder["merged_row"] = row

    def commit(self):
        self._recorder["committed"] = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestUpsertTranslation:
    def test_constructs_row_and_merges_commits(self):
        recorder: dict = {}

        def session_factory():
            return _FakeSession(recorder)

        upsert_translation(
            session_factory,
            ref_type="hadith",
            ref_key="h1",
            language="urdu",
            translated_text="translated text",
            model_name="claude-sonnet-5",
        )

        assert recorder.get("committed") is True
        row = recorder["merged_row"]
        assert row.ref_type == "hadith"
        assert row.ref_key == "h1"
        assert isinstance(row.ref_key, str)
        assert row.language == "urdu"
        assert row.translated_text == "translated text"
        assert row.source == "mt"
        assert row.model == "claude-sonnet-5"
        assert row.translated_at.tzinfo is not None
        assert row.translated_at <= datetime.now(timezone.utc)


# ================================================================
# run_batch
# ================================================================

class _FakeVector:
    def __init__(self, metadata):
        self.metadata = metadata


class _FakeFetchResponse:
    def __init__(self, vectors: dict):
        self.vectors = vectors


class _FakePineconeIndex:
    """Fake Pinecone index: `.list()` yields pages of id lists, `.fetch()` returns
    a response object with `.vectors` mapping id -> object with `.metadata`."""

    def __init__(self, items: dict[str, dict], page_size: int = 2):
        self._items = items
        self._page_size = page_size

    def list(self, namespace=None):
        ids = list(self._items.keys())
        for i in range(0, len(ids), self._page_size):
            yield ids[i : i + self._page_size]

    def fetch(self, ids, namespace=None):
        vectors = {vid: _FakeVector(self._items[vid]) for vid in ids}
        return _FakeFetchResponse(vectors)


class _FakePineconeClient:
    def __init__(self, index: _FakePineconeIndex):
        self._index = index

    def Index(self, name):
        return self._index


def _make_hadith_items(n: int) -> dict:
    return {
        f"h{i}": {"text_en": compress_text(f"hadith text {i}")}
        for i in range(n)
    }


class TestRunBatchDryRun:
    def test_dry_run_never_calls_translate_or_upsert(self):
        items = _make_hadith_items(3)
        pc_client = _FakePineconeClient(_FakePineconeIndex(items))
        languages = ["urdu", "farsi"]

        with patch("scripts.translate_references.translate_text") as mocked_translate, patch(
            "scripts.translate_references.upsert_translation"
        ) as mocked_upsert:
            summary = run_batch(
                languages=languages,
                ref_types=["hadith"],
                limit=None,
                dry_run=True,
                model_name="claude-sonnet-5",
                translation_client=None,
                pc_client=pc_client,
                session_factory=MagicMock(),
            )

        mocked_translate.assert_not_called()
        mocked_upsert.assert_not_called()
        assert summary == {"hadith": {"urdu": 3, "farsi": 3}}

    def test_limit_caps_items_processed(self):
        items = _make_hadith_items(5)
        pc_client = _FakePineconeClient(_FakePineconeIndex(items))
        languages = ["urdu"]

        with patch("scripts.translate_references.translate_text") as mocked_translate, patch(
            "scripts.translate_references.upsert_translation"
        ) as mocked_upsert:
            summary = run_batch(
                languages=languages,
                ref_types=["hadith"],
                limit=1,
                dry_run=True,
                model_name="claude-sonnet-5",
                translation_client=None,
                pc_client=pc_client,
                session_factory=MagicMock(),
            )

        mocked_translate.assert_not_called()
        mocked_upsert.assert_not_called()
        assert summary == {"hadith": {"urdu": 1}}

    def test_live_path_calls_translate_and_upsert_per_item_language(self):
        items = _make_hadith_items(2)
        pc_client = _FakePineconeClient(_FakePineconeIndex(items))
        languages = ["urdu", "farsi"]
        fake_client = MagicMock()

        with patch(
            "scripts.translate_references.translate_text", return_value="translated"
        ) as mocked_translate, patch(
            "scripts.translate_references.upsert_translation"
        ) as mocked_upsert:
            summary = run_batch(
                languages=languages,
                ref_types=["hadith"],
                limit=None,
                dry_run=False,
                model_name="claude-sonnet-5",
                translation_client=fake_client,
                pc_client=pc_client,
                session_factory=MagicMock(),
            )

        assert summary == {"hadith": {"urdu": 2, "farsi": 2}}
        # 2 items x 2 languages = 4 calls each
        assert mocked_translate.call_count == 4
        assert mocked_upsert.call_count == 4
