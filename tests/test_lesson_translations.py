"""
DEE-69 lesson/quiz/hikmah-tree translation tests.

Deterministic unit tests (mocked, no network/DB) proving:
  - `services.lesson_translation_service.lookup_lesson_translations` queries by
    (entity_type, entity_id IN (...), language[, field IN (...)]) via a mocked sync
    `Session`, and always returns a dict (never raises, even on DB error).
  - `services.lesson_translation_service.apply_translations` is a no-op (zero DB
    calls) for the default/English case, and overlays translated values onto
    objects in place otherwise, falling back to the existing source value when no
    translation row exists.
  - `services.hikmah_quiz_service.HikmahQuizService.get_questions_for_page` threads
    `language` through to the translation lookup and overlays prompt/explanation/
    choice_text onto the serialized response, with zero lookup calls for the
    default/English case.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services import lesson_translation_service
from services.hikmah_quiz_service import HikmahQuizService


def _build_query(result=None):
    query = Mock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.all.return_value = result if result is not None else []
    return query


def _translation_row(entity_id, field, translated_text):
    return SimpleNamespace(entity_id=entity_id, field=field, translated_text=translated_text)


# ================================================================
# lookup_lesson_translations
# ================================================================


class TestLookupLessonTranslations:
    def test_returns_dict_keyed_by_entity_id_and_field(self):
        db = Mock()
        db.query.return_value = _build_query(
            result=[
                _translation_row(1, "title", "translated title 1"),
                _translation_row(1, "summary", "translated summary 1"),
            ]
        )

        result = lesson_translation_service.lookup_lesson_translations(db, "lesson", [1, 2], "urdu")

        assert result == {
            (1, "title"): "translated title 1",
            (1, "summary"): "translated summary 1",
        }

    def test_returns_empty_dict_for_empty_entity_ids(self):
        db = Mock()

        result = lesson_translation_service.lookup_lesson_translations(db, "lesson", [], "urdu")

        assert result == {}
        db.query.assert_not_called()

    def test_returns_empty_dict_on_query_exception(self):
        db = Mock()
        db.query.side_effect = RuntimeError("db down")

        result = lesson_translation_service.lookup_lesson_translations(db, "lesson", [1], "urdu")

        assert result == {}

    def test_fields_arg_adds_extra_filter_call(self):
        db = Mock()
        query = _build_query(result=[])
        db.query.return_value = query

        lesson_translation_service.lookup_lesson_translations(
            db, "lesson_content", [5], "urdu", fields=["title"]
        )

        # base filter (entity_type, entity_id.in_, language) + fields filter
        assert query.filter.call_count == 2


# ================================================================
# apply_translations
# ================================================================


class TestApplyTranslations:
    def test_noop_when_language_english(self):
        db = Mock()
        obj = SimpleNamespace(id=1, title="Source Title", summary="Source Summary")

        lesson_translation_service.apply_translations(
            db, "lesson", [obj], fields=["title", "summary"], language="english"
        )

        assert obj.title == "Source Title"
        assert obj.summary == "Source Summary"
        db.query.assert_not_called()

    def test_noop_when_language_empty(self):
        db = Mock()
        obj = SimpleNamespace(id=1, title="Source Title", summary="Source Summary")

        lesson_translation_service.apply_translations(
            db, "lesson", [obj], fields=["title", "summary"], language=""
        )

        assert obj.title == "Source Title"
        assert obj.summary == "Source Summary"
        db.query.assert_not_called()

    def test_overlays_translated_field_and_falls_back_for_missing(self):
        db = Mock()
        db.query.return_value = _build_query(result=[_translation_row(1, "title", "Translated Title")])
        obj = SimpleNamespace(id=1, title="Source Title", summary="Source Summary")

        lesson_translation_service.apply_translations(
            db, "lesson", [obj], fields=["title", "summary"], language="urdu"
        )

        assert obj.title == "Translated Title"
        assert obj.summary == "Source Summary"

    def test_noop_when_objects_empty(self):
        db = Mock()

        lesson_translation_service.apply_translations(
            db, "lesson", [], fields=["title", "summary"], language="urdu"
        )

        db.query.assert_not_called()


# ================================================================
# HikmahQuizService.get_questions_for_page language threading
# ================================================================


def _build_service_db(question, choices):
    db = Mock()
    page = SimpleNamespace(id=question.lesson_content_id)
    db.get.return_value = page

    def query_side_effect(model):
        from db.models.lesson_page_quiz_questions import LessonPageQuizQuestion
        from db.models.lesson_page_quiz_choices import LessonPageQuizChoice

        if model is LessonPageQuizQuestion:
            return _build_query(result=[question])
        if model is LessonPageQuizChoice:
            return _build_query(result=choices)
        return _build_query(result=[])

    db.query.side_effect = query_side_effect
    return db


def _sample_question_and_choices():
    question = SimpleNamespace(
        id=100,
        lesson_content_id=12,
        prompt="Sample prompt",
        order_position=1,
        explanation="Sample explanation",
        is_active=True,
        tags=["topic"],
    )
    choice_a = SimpleNamespace(id=200, question_id=100, choice_key="A", choice_text="A text", order_position=1, is_correct=True)
    choice_b = SimpleNamespace(id=201, question_id=100, choice_key="B", choice_text="B text", order_position=2, is_correct=False)
    return question, [choice_a, choice_b]


class TestGetQuestionsForPageTranslation:
    def test_language_none_returns_untouched_payload_with_zero_lookup_calls(self, monkeypatch):
        question, choices = _sample_question_and_choices()
        db = _build_service_db(question, choices)

        mock_lookup = Mock(return_value={})
        monkeypatch.setattr(
            "services.hikmah_quiz_service.lesson_translation_service.lookup_lesson_translations",
            mock_lookup,
        )

        service = HikmahQuizService(db)
        result = service.get_questions_for_page(12, language=None)

        assert result["questions"][0]["prompt"] == "Sample prompt"
        assert result["questions"][0]["explanation"] == "Sample explanation"
        assert result["questions"][0]["choices"][0]["choice_text"] == "A text"
        mock_lookup.assert_not_called()

    def test_language_english_returns_untouched_payload_with_zero_lookup_calls(self, monkeypatch):
        question, choices = _sample_question_and_choices()
        db = _build_service_db(question, choices)

        mock_lookup = Mock(return_value={})
        monkeypatch.setattr(
            "services.hikmah_quiz_service.lesson_translation_service.lookup_lesson_translations",
            mock_lookup,
        )

        service = HikmahQuizService(db)
        result = service.get_questions_for_page(12, language="english")

        assert result["questions"][0]["prompt"] == "Sample prompt"
        mock_lookup.assert_not_called()

    def test_language_urdu_overlays_prompt_explanation_and_choice_text(self, monkeypatch):
        question, choices = _sample_question_and_choices()
        db = _build_service_db(question, choices)

        def fake_lookup(db_arg, entity_type, entity_ids, language, fields=None):
            if entity_type == "quiz_question":
                return {(100, "prompt"): "Translated prompt", (100, "explanation"): "Translated explanation"}
            if entity_type == "quiz_choice":
                return {(200, "choice_text"): "Translated A text"}
            return {}

        monkeypatch.setattr(
            "services.hikmah_quiz_service.lesson_translation_service.lookup_lesson_translations",
            fake_lookup,
        )

        service = HikmahQuizService(db)
        result = service.get_questions_for_page(12, language="urdu")

        q = result["questions"][0]
        assert q["prompt"] == "Translated prompt"
        assert q["explanation"] == "Translated explanation"
        assert q["choices"][0]["choice_text"] == "Translated A text"
        # No matching translation row for choice 201 -> fallback to source
        assert q["choices"][1]["choice_text"] == "B text"

    def test_admin_methods_do_not_accept_language_param(self):
        import inspect

        for method_name in [
            "list_questions_for_page_admin",
            "get_question_for_page",
            "create_question",
            "replace_question",
            "patch_question",
            "delete_question",
        ]:
            sig = inspect.signature(getattr(HikmahQuizService, method_name))
            assert "language" not in sig.parameters
