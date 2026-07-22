"""
DEE-69 batch MT script tests.

Deterministic unit tests (mocked, no network/DB) for scripts/translate_lessons.py:
CLI parsing, entity-type resolution, translate_text() claude-CLI subprocess mock
(including the hardened Qur'an-preservation system prompt), upsert_translation()'s
idempotent merge/commit shape, dry-run safety (never calls the claude CLI or writes to
the DB), --limit sampling, and source_hash-based staleness skip/re-translate.
Also covers core.utils.source_text_hash.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.utils import source_text_hash
from db.models.lesson_content import LessonContent
from db.models.lessons import Lesson
from scripts.translate_lessons import (
    CLAUDE_TIMEOUT_SECONDS,
    DEFAULT_MODEL,
    ENTITY_FIELD_MAP,
    ENTITY_TYPE_CHOICES,
    SUPPORTED_LANGUAGES,
    _resolve_enabled_entity_types,
    parse_args,
    run_batch,
    translate_text,
    upsert_translation,
)


# ================================================================
# core.utils.source_text_hash
# ================================================================


class TestSourceTextHash:
    def test_deterministic_for_same_input(self):
        assert source_text_hash("some text") == source_text_hash("some text")

    def test_different_input_yields_different_hash(self):
        assert source_text_hash("some text") != source_text_hash("other text")

    def test_empty_and_none_hash_the_same_deterministic_value(self):
        assert source_text_hash("") == source_text_hash(None)
        assert source_text_hash(None) != ""


# ================================================================
# parse_args
# ================================================================


class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.languages == ",".join(SUPPORTED_LANGUAGES)
        assert args.entity_type == "all"
        assert args.dry_run is False
        assert args.model == DEFAULT_MODEL
        assert args.limit is None


# ================================================================
# _resolve_enabled_entity_types
# ================================================================


class TestResolveEnabledEntityTypes:
    def test_all_returns_every_entity_type_in_table_order(self):
        assert _resolve_enabled_entity_types("all") == [
            "lesson",
            "lesson_content",
            "quiz_question",
            "quiz_choice",
            "hikmah_tree",
        ]
        assert _resolve_enabled_entity_types("all") == ENTITY_TYPE_CHOICES

    def test_single_entity_type_passthrough(self):
        assert _resolve_enabled_entity_types("hikmah_tree") == ["hikmah_tree"]


# ================================================================
# translate_text
# ================================================================


class TestTranslateText:
    def test_calls_subprocess_with_expected_command_and_returns_stripped_output(self):
        fake_result = SimpleNamespace(returncode=0, stdout="  translated output  ", stderr="")
        with patch("scripts.translate_lessons.subprocess.run", return_value=fake_result) as mocked_run:
            result = translate_text(model="sonnet", text="source text", language="urdu")

        assert result == "translated output"
        mocked_run.assert_called_once()
        args, kwargs = mocked_run.call_args
        command = args[0]
        for expected in ["claude", "-p", "--model", "sonnet", "--system-prompt", "--safe-mode", "--tools", "", "--no-session-persistence"]:
            assert expected in command

        system_prompt_index = command.index("--system-prompt") + 1
        system_prompt = command[system_prompt_index]
        assert "urdu" in system_prompt
        assert "Qur'an" in system_prompt or "Qur’an" in system_prompt
        assert "verbatim" in system_prompt.lower() or "EXACTLY" in system_prompt

        assert kwargs["input"] == "source text"
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == CLAUDE_TIMEOUT_SECONDS

    def test_raises_on_nonzero_returncode(self):
        fake_result = SimpleNamespace(returncode=1, stdout="", stderr="boom")
        with patch("scripts.translate_lessons.subprocess.run", return_value=fake_result):
            try:
                translate_text(model="sonnet", text="text", language="urdu")
                assert False, "expected RuntimeError"
            except RuntimeError as exc:
                assert "claude CLI exited" in str(exc)

    def test_raises_on_empty_output(self):
        fake_result = SimpleNamespace(returncode=0, stdout="   ", stderr="")
        with patch("scripts.translate_lessons.subprocess.run", return_value=fake_result):
            try:
                translate_text(model="sonnet", text="text", language="urdu")
                assert False, "expected RuntimeError"
            except RuntimeError as exc:
                assert "empty output" in str(exc)


# ================================================================
# upsert_translation
# ================================================================


class _FakeUpsertSession:
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
            return _FakeUpsertSession(recorder)

        upsert_translation(
            session_factory,
            entity_type="lesson_content",
            entity_id=5,
            field="content_body",
            language="urdu",
            translated_text="translated body",
            model_name="sonnet",
            source_hash="abc123",
        )

        assert recorder.get("committed") is True
        row = recorder["merged_row"]
        assert row.entity_type == "lesson_content"
        assert row.entity_id == 5
        assert row.field == "content_body"
        assert row.language == "urdu"
        assert row.translated_text == "translated body"
        assert row.source == "mt"
        assert row.model == "sonnet"
        assert row.source_hash == "abc123"
        assert row.translated_at.tzinfo is not None
        assert row.translated_at <= datetime.now(timezone.utc)


# ================================================================
# run_batch
# ================================================================


class _FakeSourceRow:
    def __init__(self, id, **fields):
        self.id = id
        for key, value in fields.items():
            setattr(self, key, value)


class _FakeSourceQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def all(self):
        return self._rows


class _FakeRunBatchSession:
    """Fake session used by _iter_source_rows: `.query(model_cls)` returns rows
    configured for that model class. `_existing_source_hash` is monkeypatched
    directly in these tests rather than faked through this session's query chain,
    since it targets a column expression (`LessonTranslation.source_hash`), not a
    full model class."""

    def __init__(self, rows_by_model: dict):
        self._rows_by_model = rows_by_model

    def query(self, model_cls):
        return _FakeSourceQuery(self._rows_by_model.get(model_cls, []))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _make_session_factory(rows_by_model: dict):
    def factory():
        return _FakeRunBatchSession(rows_by_model)
    return factory


def _lesson_content_rows(n: int):
    return [
        _FakeSourceRow(id=i, title=f"Title {i}", content_body=f"Body {i}")
        for i in range(1, n + 1)
    ]


def _lesson_rows(n: int):
    return [
        _FakeSourceRow(id=i, title=f"Lesson Title {i}", summary=f"Lesson Summary {i}")
        for i in range(1, n + 1)
    ]


class TestRunBatchDryRun:
    def test_dry_run_never_calls_translate_or_upsert(self):
        rows = _lesson_content_rows(2)
        session_factory = _make_session_factory({LessonContent: rows})

        with patch("scripts.translate_lessons.translate_text") as mocked_translate, patch(
            "scripts.translate_lessons.upsert_translation"
        ) as mocked_upsert, patch(
            "scripts.translate_lessons._existing_source_hash", return_value=None
        ):
            summary = run_batch(
                languages=["urdu", "farsi"],
                entity_types=["lesson_content"],
                limit=None,
                dry_run=True,
                model_name="sonnet",
                session_factory=session_factory,
            )

        mocked_translate.assert_not_called()
        mocked_upsert.assert_not_called()
        # 2 rows x 2 fields (title, content_body) = 4 items per language
        assert summary == {"lesson_content": {"urdu": 4, "farsi": 4}}

    def test_limit_caps_items_processed(self):
        rows = _lesson_rows(5)
        session_factory = _make_session_factory({Lesson: rows})

        with patch("scripts.translate_lessons.translate_text") as mocked_translate, patch(
            "scripts.translate_lessons.upsert_translation"
        ) as mocked_upsert, patch(
            "scripts.translate_lessons._existing_source_hash", return_value=None
        ):
            summary = run_batch(
                languages=["urdu"],
                entity_types=["lesson"],
                limit=1,
                dry_run=True,
                model_name="sonnet",
                session_factory=session_factory,
            )

        mocked_translate.assert_not_called()
        mocked_upsert.assert_not_called()
        # 1 row (limit) x 2 fields (title, summary) = 2 items
        assert summary == {"lesson": {"urdu": 2}}


class TestRunBatchStaleness:
    def test_unchanged_source_hash_is_skipped(self):
        row = _FakeSourceRow(id=1, title="Same Title", content_body="Same Body")
        session_factory = _make_session_factory({LessonContent: [row]})

        title_hash = source_text_hash("Same Title")

        def fake_existing_hash(session, entity_type, entity_id, field, language):
            if field == "title":
                return title_hash  # matches computed hash -> stale check says "unchanged"
            return None  # content_body has no existing row -> needs translation

        with patch(
            "scripts.translate_lessons.translate_text", return_value="translated"
        ) as mocked_translate, patch(
            "scripts.translate_lessons.upsert_translation"
        ) as mocked_upsert, patch(
            "scripts.translate_lessons._existing_source_hash", side_effect=fake_existing_hash
        ):
            summary = run_batch(
                languages=["urdu"],
                entity_types=["lesson_content"],
                limit=None,
                dry_run=False,
                model_name="sonnet",
                session_factory=session_factory,
            )

        # Only content_body needed translation (title was skipped as unchanged)
        assert summary == {"lesson_content": {"urdu": 1}}
        mocked_translate.assert_called_once()
        mocked_upsert.assert_called_once()
        _, upsert_kwargs = mocked_upsert.call_args
        assert upsert_kwargs["field"] == "content_body"
        assert upsert_kwargs["source_hash"] == source_text_hash("Same Body")

    def test_changed_source_hash_is_retranslated(self):
        row = _FakeSourceRow(id=1, title="New Title", content_body="Same Body")
        session_factory = _make_session_factory({LessonContent: [row]})

        with patch(
            "scripts.translate_lessons.translate_text", return_value="translated"
        ) as mocked_translate, patch(
            "scripts.translate_lessons.upsert_translation"
        ) as mocked_upsert, patch(
            "scripts.translate_lessons._existing_source_hash", return_value="stale-hash-does-not-match"
        ):
            summary = run_batch(
                languages=["urdu"],
                entity_types=["lesson_content"],
                limit=None,
                dry_run=False,
                model_name="sonnet",
                session_factory=session_factory,
            )

        assert summary == {"lesson_content": {"urdu": 2}}
        assert mocked_translate.call_count == 2
        assert mocked_upsert.call_count == 2


class TestRunBatchLivePath:
    def test_live_path_calls_translate_and_upsert_per_row_field_language(self):
        rows = _lesson_rows(2)
        session_factory = _make_session_factory({Lesson: rows})

        with patch(
            "scripts.translate_lessons.translate_text", return_value="translated"
        ) as mocked_translate, patch(
            "scripts.translate_lessons.upsert_translation"
        ) as mocked_upsert, patch(
            "scripts.translate_lessons._existing_source_hash", return_value=None
        ):
            summary = run_batch(
                languages=["urdu", "farsi"],
                entity_types=["lesson"],
                limit=None,
                dry_run=False,
                model_name="sonnet",
                session_factory=session_factory,
            )

        # 2 rows x 2 fields x 2 languages = 8 combinations
        assert summary == {"lesson": {"urdu": 4, "farsi": 4}}
        assert mocked_translate.call_count == 8
        assert mocked_upsert.call_count == 8

        rows_by_id = {row.id: row for row in rows}
        for call in mocked_upsert.call_args_list:
            _, kwargs = call
            source_row = rows_by_id[kwargs["entity_id"]]
            source_text = getattr(source_row, kwargs["field"])
            assert kwargs["source_hash"] == source_text_hash(source_text)
