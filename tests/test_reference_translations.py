"""
DEE-67 reference-translation tests.

Deterministic unit tests (mocked, no network/DB) proving:
  - `services.reference_translation_service.alookup_translations` opens its own
    AsyncSessionLocal, queries by (ref_type, ref_key IN (...), language), and always
    returns a dict (never raises, even on DB error).
  - `core.utils.aformat_references_as_json` / `aformat_quran_references_as_json` skip
    the DB call entirely when no non-English language is selected, and otherwise merge
    translations onto the existing base formatter output without touching existing
    fields.
  - `core.pipeline.references_pipeline` threads `language` through to the async
    formatter.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeRow:
    def __init__(self, ref_key: str, translated_text: str):
        self.ref_key = ref_key
        self.translated_text = translated_text


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeAsyncSession:
    """Fake async-context-manager AsyncSession stub. `execute` is an AsyncMock so
    callers can configure return_value or side_effect per test."""

    def __init__(self, rows=None, raise_exc=None):
        self._rows = rows or []
        self._raise_exc = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt):
        if self._raise_exc is not None:
            raise self._raise_exc
        return _FakeResult(self._rows)


def _make_session_factory(rows=None, raise_exc=None):
    def factory():
        return _FakeAsyncSession(rows=rows, raise_exc=raise_exc)
    return factory


class TestAlookupTranslations:
    @pytest.mark.asyncio
    async def test_returns_dict_when_rows_exist(self):
        from services import reference_translation_service

        rows = [_FakeRow("h1", "translated h1"), _FakeRow("h2", "translated h2")]
        with patch.object(
            reference_translation_service,
            "AsyncSessionLocal",
            _make_session_factory(rows=rows),
        ):
            result = await reference_translation_service.alookup_translations(
                "hadith", ["h1", "h2"], "urdu"
            )

        assert result == {"h1": "translated h1", "h2": "translated h2"}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_db_exception(self):
        from services import reference_translation_service

        with patch.object(
            reference_translation_service,
            "AsyncSessionLocal",
            _make_session_factory(raise_exc=RuntimeError("db down")),
        ):
            result = await reference_translation_service.alookup_translations(
                "hadith", ["h1"], "urdu"
            )

        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_for_empty_ref_keys(self):
        from services import reference_translation_service

        # AsyncSessionLocal should never even be opened for empty input.
        with patch.object(
            reference_translation_service,
            "AsyncSessionLocal",
            _make_session_factory(rows=[_FakeRow("h1", "should not be reached")]),
        ) as mocked_factory:
            result = await reference_translation_service.alookup_translations(
                "hadith", [], "urdu"
            )

        assert result == {}


class TestAformatReferencesAsJson:
    def _base_docs(self):
        return [
            {
                "metadata": {"hadith_id": "h1", "sect": "shia"},
                "page_content_en": "text one",
                "page_content_ar": "arabic one",
            },
            {
                "metadata": {"hadith_id": "h2", "sect": "shia"},
                "page_content_en": "text two",
                "page_content_ar": "arabic two",
            },
        ]

    @pytest.mark.asyncio
    async def test_language_none_skips_db_call(self):
        from core import utils

        docs = self._base_docs()
        with patch(
            "core.utils.reference_translation_service.alookup_translations",
            new=AsyncMock(),
        ) as mocked_lookup:
            result = await utils.aformat_references_as_json(docs, language=None)

        mocked_lookup.assert_not_called()
        assert len(result) == 2
        for ref in result:
            assert ref["text_translated"] is None
            assert ref["translated_language"] is None
        # existing fields unchanged
        assert result[0]["text"] == "text one"
        assert result[0]["text_ar"] == "arabic one"

    @pytest.mark.asyncio
    async def test_language_english_skips_db_call(self):
        from core import utils

        docs = self._base_docs()
        with patch(
            "core.utils.reference_translation_service.alookup_translations",
            new=AsyncMock(),
        ) as mocked_lookup:
            result = await utils.aformat_references_as_json(docs, language="english")

        mocked_lookup.assert_not_called()
        for ref in result:
            assert ref["text_translated"] is None
            assert ref["translated_language"] is None

    @pytest.mark.asyncio
    async def test_language_urdu_calls_lookup_once_and_merges(self):
        from core import utils

        docs = self._base_docs()
        with patch(
            "core.utils.reference_translation_service.alookup_translations",
            new=AsyncMock(return_value={"h1": "translated h1"}),
        ) as mocked_lookup:
            result = await utils.aformat_references_as_json(docs, language="urdu")

        mocked_lookup.assert_called_once_with("hadith", ["h1", "h2"], "urdu")
        assert result[0]["text_translated"] == "translated h1"
        assert result[0]["translated_language"] == "urdu"
        # no matching translation row -> fallback to None
        assert result[1]["text_translated"] is None
        assert result[1]["translated_language"] == "urdu"
        # existing fields still unchanged
        assert result[0]["text"] == "text one"
        assert result[1]["text_ar"] == "arabic two"


class TestAformatQuranReferencesAsJson:
    def _base_docs(self):
        return [
            {
                "chunk_id": "c1",
                "metadata": {"surah_name": "Al-Fatiha"},
                "quran_translation": "verse one",
                "page_content_en": "tafsir one",
            },
            {
                "chunk_id": "c2",
                "metadata": {"surah_name": "Al-Baqarah"},
                "quran_translation": "verse two",
                "page_content_en": "tafsir two",
            },
        ]

    @pytest.mark.asyncio
    async def test_language_none_skips_db_call(self):
        from core import utils

        docs = self._base_docs()
        with patch(
            "core.utils.reference_translation_service.alookup_translations",
            new=AsyncMock(),
        ) as mocked_lookup:
            result = await utils.aformat_quran_references_as_json(docs, language=None)

        mocked_lookup.assert_not_called()
        for ref in result:
            assert ref["quran_translation_translated"] is None
            assert ref["tafsir_text_translated"] is None
            assert ref["translated_language"] is None
        assert result[0]["quran_translation"] == "verse one"
        assert result[0]["tafsir_text"] == "tafsir one"

    @pytest.mark.asyncio
    async def test_language_urdu_calls_lookup_twice_and_merges(self):
        from core import utils

        docs = self._base_docs()

        async def fake_lookup(ref_type, ref_keys, language):
            if ref_type == "quran_translation":
                return {"c1": "translated verse one"}
            if ref_type == "tafsir_text":
                return {"c2": "translated tafsir two"}
            return {}

        with patch(
            "core.utils.reference_translation_service.alookup_translations",
            new=AsyncMock(side_effect=fake_lookup),
        ) as mocked_lookup:
            result = await utils.aformat_quran_references_as_json(docs, language="urdu")

        assert mocked_lookup.call_count == 2
        call_ref_types = {call.args[0] for call in mocked_lookup.call_args_list}
        assert call_ref_types == {"quran_translation", "tafsir_text"}

        assert result[0]["quran_translation_translated"] == "translated verse one"
        assert result[0]["tafsir_text_translated"] is None
        assert result[1]["quran_translation_translated"] is None
        assert result[1]["tafsir_text_translated"] == "translated tafsir two"
        for ref in result:
            assert ref["translated_language"] == "urdu"
        # existing fields unchanged
        assert result[0]["quran_translation"] == "verse one"
        assert result[1]["tafsir_text"] == "tafsir two"


class TestReferencesPipelineLanguageThreading:
    @pytest.mark.asyncio
    async def test_language_reaches_formatter(self):
        from core import pipeline

        with patch(
            "core.pipeline.classifier.aclassify_non_islamic_query",
            new=AsyncMock(return_value=False),
        ), patch(
            "core.pipeline.enhancer.aenhance_query",
            new=AsyncMock(return_value="enhanced query"),
        ), patch(
            "core.pipeline.retriever.aretrieve_shia_documents",
            new=AsyncMock(return_value=[]),
        ), patch(
            "core.pipeline.utils.aformat_references_as_json",
            new=AsyncMock(return_value=[]),
        ) as mocked_formatter:
            await pipeline.references_pipeline("test query", "shia", 10, language="urdu")

        mocked_formatter.assert_called_once_with([], "urdu")
