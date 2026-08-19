import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from db.models.lesson_content import LessonContent
from db.models.lessons import Lesson
from db.models.lesson_page_quiz_questions import LessonPageQuizQuestion
from db.models.lesson_page_quiz_choices import LessonPageQuizChoice
from db.models.lesson_page_quiz_attempts import LessonPageQuizAttempt
from db.session import SessionLocal
from services import lesson_translation_service

logger = logging.getLogger(__name__)


class HikmahQuizService:
    """Service for lesson-page quiz retrieval, authoring CRUD, and answer processing."""

    def __init__(self, db: Session):
        self.db = db

    # -----------------------------
    # Learner-facing retrieval APIs
    # -----------------------------
    def get_questions_for_page(
        self, lesson_content_id: int, language: Optional[str] = None
    ) -> Dict[str, Any]:
        """Return active quiz questions for a lesson content page."""
        questions = self._list_questions_for_page_models(
            lesson_content_id=lesson_content_id,
            include_inactive=False,
        )

        serialized = self._serialize_questions(questions, include_admin_fields=False)
        self._apply_quiz_translations(serialized, language)

        return {
            "lesson_content_id": lesson_content_id,
            "questions": serialized,
        }

    # ---------------------
    # Authoring CRUD methods
    # ---------------------
    def create_question(self, lesson_content_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a quiz question with choices for a lesson page."""
        self._ensure_page_exists(lesson_content_id)
        choices_payload = payload.get("choices") or []
        self._validate_choices_payload(choices_payload)

        question = LessonPageQuizQuestion(
            lesson_content_id=lesson_content_id,
            prompt=payload["prompt"],
            explanation=payload.get("explanation"),
            tags=payload.get("tags"),
            order_position=payload.get("order_position", 1),
            is_active=payload.get("is_active", True),
        )

        try:
            self.db.add(question)
            self.db.flush()

            for choice in choices_payload:
                self.db.add(
                    LessonPageQuizChoice(
                        question_id=question.id,
                        choice_key=choice["choice_key"],
                        choice_text=choice["choice_text"],
                        order_position=choice.get("order_position", 1),
                        is_correct=choice.get("is_correct", False),
                    )
                )

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return self.get_question_for_page(lesson_content_id, int(question.id))

    def list_questions_for_page_admin(
        self,
        lesson_content_id: int,
        include_inactive: bool = False,
    ) -> Dict[str, Any]:
        """List quiz questions for a page in authoring view."""
        questions = self._list_questions_for_page_models(
            lesson_content_id=lesson_content_id,
            include_inactive=include_inactive,
        )

        return {
            "lesson_content_id": lesson_content_id,
            "questions": self._serialize_questions(questions, include_admin_fields=True),
        }

    def get_question_for_page(self, lesson_content_id: int, question_id: int) -> Dict[str, Any]:
        """Get one quiz question for a page in authoring view."""
        self._ensure_page_exists(lesson_content_id)
        question = self._get_question_for_page(lesson_content_id, question_id)
        choices_by_question = self._get_choices_by_question_ids([question.id])
        choices = choices_by_question.get(question.id, [])
        return self._serialize_question(
            question,
            choices,
            include_admin_fields=True,
        )

    def replace_question(
        self,
        lesson_content_id: int,
        question_id: int,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Full replace of question metadata and choices."""
        self._ensure_page_exists(lesson_content_id)
        question = self._get_question_for_page(lesson_content_id, question_id)

        choices_payload = payload.get("choices") or []
        self._validate_choices_payload(choices_payload)

        has_attempts = (
            self.db.query(LessonPageQuizAttempt)
            .filter(LessonPageQuizAttempt.question_id == question_id)
            .first()
        )
        if has_attempts:
            raise ValueError("Cannot replace choices for a question that already has attempts")

        question.prompt = payload["prompt"]
        question.explanation = payload.get("explanation")
        question.tags = payload.get("tags")
        question.order_position = payload.get("order_position", 1)
        question.is_active = payload.get("is_active", True)

        try:
            (
                self.db.query(LessonPageQuizChoice)
                .filter(LessonPageQuizChoice.question_id == question_id)
                .delete(synchronize_session=False)
            )

            for choice in choices_payload:
                self.db.add(
                    LessonPageQuizChoice(
                        question_id=question_id,
                        choice_key=choice["choice_key"],
                        choice_text=choice["choice_text"],
                        order_position=choice.get("order_position", 1),
                        is_correct=choice.get("is_correct", False),
                    )
                )

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return self.get_question_for_page(lesson_content_id, question_id)

    def patch_question(
        self,
        lesson_content_id: int,
        question_id: int,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Partial update for question metadata (choices are unchanged)."""
        self._ensure_page_exists(lesson_content_id)
        question = self._get_question_for_page(lesson_content_id, question_id)

        for field in ["prompt", "explanation", "tags", "order_position", "is_active"]:
            if field in payload:
                setattr(question, field, payload[field])

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return self.get_question_for_page(lesson_content_id, question_id)

    def delete_question(self, lesson_content_id: int, question_id: int) -> None:
        """Hard delete question (DB cascades choices and attempts)."""
        self._ensure_page_exists(lesson_content_id)
        question = self._get_question_for_page(lesson_content_id, question_id)

        try:
            self.db.delete(question)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    # ------------------------
    # Submission + memory flow
    # ------------------------
    def process_submission(
        self,
        lesson_content_id: int,
        user_id: str,
        question_id: int,
        selected_choice_id: int,
        answered_at: Optional[datetime] = None,
    ) -> None:
        """Process a quiz submission: validate, persist attempt, and trigger memory if needed."""
        page = self.db.get(LessonContent, lesson_content_id)
        if not page:
            logger.warning(
                "Quiz submit ignored: page not found",
                extra={
                    "lesson_content_id": lesson_content_id,
                    "question_id": question_id,
                    "selected_choice_id": selected_choice_id,
                    "user_id": user_id,
                },
            )
            return

        question = (
            self.db.query(LessonPageQuizQuestion)
            .filter(
                LessonPageQuizQuestion.id == question_id,
                LessonPageQuizQuestion.lesson_content_id == lesson_content_id,
                LessonPageQuizQuestion.is_active.is_(True),
            )
            .first()
        )
        if not question:
            logger.warning(
                "Quiz submit ignored: question not found for page",
                extra={
                    "lesson_content_id": lesson_content_id,
                    "question_id": question_id,
                    "selected_choice_id": selected_choice_id,
                    "user_id": user_id,
                },
            )
            return

        selected_choice = (
            self.db.query(LessonPageQuizChoice)
            .filter(
                LessonPageQuizChoice.id == selected_choice_id,
                LessonPageQuizChoice.question_id == question_id,
            )
            .first()
        )
        if not selected_choice:
            logger.warning(
                "Quiz submit ignored: selected choice not found for question",
                extra={
                    "lesson_content_id": lesson_content_id,
                    "question_id": question_id,
                    "selected_choice_id": selected_choice_id,
                    "user_id": user_id,
                },
            )
            return

        correct_choice = (
            self.db.query(LessonPageQuizChoice)
            .filter(
                LessonPageQuizChoice.question_id == question_id,
                LessonPageQuizChoice.is_correct.is_(True),
            )
            .first()
        )
        if not correct_choice:
            logger.warning(
                "Quiz submit ignored: no correct choice configured",
                extra={
                    "lesson_content_id": lesson_content_id,
                    "question_id": question_id,
                    "selected_choice_id": selected_choice_id,
                    "user_id": user_id,
                },
            )
            return

        answered_at_utc = self._to_utc(answered_at)
        is_correct = bool(selected_choice.is_correct)

        attempt = LessonPageQuizAttempt(
            user_id=user_id,
            lesson_content_id=lesson_content_id,
            question_id=question_id,
            selected_choice_id=selected_choice_id,
            is_correct=is_correct,
            answered_at=answered_at_utc,
        )
        self.db.add(attempt)
        self.db.commit()

        if is_correct:
            return

        lesson = self.db.get(Lesson, page.lesson_id) if page.lesson_id else None
        topics_tested = question.tags or (lesson.tags if lesson and lesson.tags else [])

        # Snapshot everything the memory event needs as plain values BEFORE
        # releasing the DB connection. The LLM memory analysis can take several
        # seconds, and we must not hold a pooled connection during it (Supabase
        # session mode caps clients at 15). See _trigger_incorrect_quiz_memory_event.
        memory_payload = {
            "user_id": user_id,
            "lesson_content_id": lesson_content_id,
            "lesson_id": page.lesson_id,
            "topics_tested": topics_tested,
            "question_id": int(question.id),
            "question_prompt": question.prompt,
            "selected_choice_id": int(selected_choice.id),
            "selected_choice_key": selected_choice.choice_key,
            "selected_choice_text": selected_choice.choice_text,
            "correct_choice_id": int(correct_choice.id),
            "correct_choice_key": correct_choice.choice_key,
            "correct_choice_text": correct_choice.choice_text,
        }

        # Release this session's connection back to the pool before the long LLM
        # call. The reads above (e.g. self.db.get(Lesson, ...)) opened a new
        # read-only transaction; rollback ends it and frees the connection.
        # (Use rollback, not close — process_quiz_submission_background owns the
        # close in its finally block.)
        self.db.rollback()

        try:
            asyncio.run(self._trigger_incorrect_quiz_memory_event(**memory_payload))
        except Exception:
            logger.exception(
                "Failed to process incorrect quiz memory event",
                extra={
                    "lesson_content_id": lesson_content_id,
                    "question_id": question_id,
                    "selected_choice_id": selected_choice_id,
                    "user_id": user_id,
                },
            )

    async def _trigger_incorrect_quiz_memory_event(
        self,
        user_id: str,
        lesson_content_id: int,
        lesson_id: Optional[int],
        topics_tested: List[str],
        question_id: int,
        question_prompt: str,
        selected_choice_id: int,
        selected_choice_key: str,
        selected_choice_text: str,
        correct_choice_id: int,
        correct_choice_key: str,
        correct_choice_text: str,
    ) -> None:
        from agents.core.universal_memory_agent import UniversalMemoryAgent, InteractionType

        quiz_id = f"page:{lesson_content_id}:question:{question_id}"
        interaction_data = {
            "quiz_id": quiz_id,
            "lesson_id": str(lesson_id) if lesson_id is not None else None,
            "score": 0.0,
            "total_questions": 1,
            "correct_answers": 0,
            "topics_tested": topics_tested,
            "incorrect_topics": topics_tested,
            "question_details": [
                {
                    "question_id": question_id,
                    "prompt": question_prompt,
                    "selected_choice": {
                        "id": selected_choice_id,
                        "key": selected_choice_key,
                        "text": selected_choice_text,
                    },
                    "correct_choice": {
                        "id": correct_choice_id,
                        "key": correct_choice_key,
                        "text": correct_choice_text,
                    },
                }
            ],
        }

        context = {
            "source": "hikmah_page_quiz",
            "lesson_content_id": int(lesson_content_id),
            "question_prompt": question_prompt,
            "selected_choice_text": selected_choice_text,
            "correct_choice_text": correct_choice_text,
        }

        # Run the LLM memory analysis on its OWN short-lived session so the long
        # inference never holds the quiz path's pooled connection. Mirrors the
        # pattern in modules/generation/stream_generator.py::_update_hikmah_memory.
        memory_db = SessionLocal()
        try:
            memory_agent = UniversalMemoryAgent(memory_db)
            await memory_agent.analyze_interaction(
                user_id=user_id,
                interaction_type=InteractionType.QUIZ_RESULT,
                interaction_data=interaction_data,
                context=context,
            )
        finally:
            memory_db.close()

    # ------------------
    # Internal utilities
    # ------------------
    def _ensure_page_exists(self, lesson_content_id: int) -> LessonContent:
        page = self.db.get(LessonContent, lesson_content_id)
        if not page:
            raise LookupError("Lesson content page not found")
        return page

    def _get_question_for_page(self, lesson_content_id: int, question_id: int) -> LessonPageQuizQuestion:
        question = (
            self.db.query(LessonPageQuizQuestion)
            .filter(
                LessonPageQuizQuestion.lesson_content_id == lesson_content_id,
                LessonPageQuizQuestion.id == question_id,
            )
            .first()
        )
        if not question:
            raise LookupError("Quiz question not found for lesson page")
        return question

    def _list_questions_for_page_models(
        self,
        lesson_content_id: int,
        include_inactive: bool,
    ) -> List[LessonPageQuizQuestion]:
        self._ensure_page_exists(lesson_content_id)

        query = self.db.query(LessonPageQuizQuestion).filter(
            LessonPageQuizQuestion.lesson_content_id == lesson_content_id
        )
        if not include_inactive:
            query = query.filter(LessonPageQuizQuestion.is_active.is_(True))

        return (
            query.order_by(
                LessonPageQuizQuestion.order_position.asc(),
                LessonPageQuizQuestion.id.asc(),
            ).all()
        )

    def _validate_choices_payload(self, choices_payload: List[Dict[str, Any]]) -> None:
        if len(choices_payload) < 2:
            raise ValueError("A quiz question must include at least 2 choices")

        correct_count = sum(1 for choice in choices_payload if choice.get("is_correct", False))
        if correct_count != 1:
            raise ValueError("Exactly one choice must be marked as correct")

        keys = [choice.get("choice_key") for choice in choices_payload]
        if len(set(keys)) != len(keys):
            raise ValueError("Each choice_key must be unique within a question")

    def _get_choices_by_question_ids(
        self,
        question_ids: List[int],
    ) -> Dict[int, List[LessonPageQuizChoice]]:
        if not question_ids:
            return {}

        all_choices = (
            self.db.query(LessonPageQuizChoice)
            .filter(LessonPageQuizChoice.question_id.in_(question_ids))
            .order_by(
                LessonPageQuizChoice.question_id.asc(),
                LessonPageQuizChoice.order_position.asc(),
                LessonPageQuizChoice.id.asc(),
            )
            .all()
        )

        choices_by_question: Dict[int, List[LessonPageQuizChoice]] = {}
        for choice in all_choices:
            choices_by_question.setdefault(choice.question_id, []).append(choice)
        return choices_by_question

    def _serialize_questions(
        self,
        questions: List[LessonPageQuizQuestion],
        include_admin_fields: bool,
    ) -> List[Dict[str, Any]]:
        if not questions:
            return []

        question_ids = [question.id for question in questions]
        choices_by_question = self._get_choices_by_question_ids(question_ids)

        return [
            self._serialize_question(
                question,
                choices_by_question.get(question.id, []),
                include_admin_fields=include_admin_fields,
            )
            for question in questions
        ]

    def _serialize_question(
        self,
        question: LessonPageQuizQuestion,
        question_choices: List[LessonPageQuizChoice],
        include_admin_fields: bool,
    ) -> Dict[str, Any]:
        correct_choice = next((choice for choice in question_choices if choice.is_correct), None)
        if not correct_choice:
            raise ValueError(f"Quiz question id={question.id} has no correct choice configured")

        payload: Dict[str, Any] = {
            "id": int(question.id),
            "prompt": question.prompt,
            "order_position": int(question.order_position),
            "choices": [
                {
                    "id": int(choice.id),
                    "choice_key": choice.choice_key,
                    "choice_text": choice.choice_text,
                    "order_position": int(choice.order_position),
                }
                for choice in question_choices
            ],
            "correct_choice_id": int(correct_choice.id),
            "explanation": question.explanation,
        }

        if include_admin_fields:
            payload.update(
                {
                    "lesson_content_id": int(question.lesson_content_id),
                    "tags": question.tags,
                    "is_active": bool(question.is_active),
                }
            )

        return payload

    def _apply_quiz_translations(
        self,
        serialized_questions: List[Dict[str, Any]],
        language: Optional[str],
    ) -> None:
        """Overlay translated prompt/explanation/choice_text onto already-serialized
        quiz question dicts, in place. No-op (zero lookup calls) when `language` is
        empty/None/"english" or there are no questions -- mirrors
        `lesson_translation_service.apply_translations`'s zero-added-DB-calls
        guarantee. Missing translation rows leave the existing source value
        untouched (EN/AR fallback)."""
        normalized = (language or "").strip().lower()
        if not normalized or normalized == "english" or not serialized_questions:
            return

        question_ids = [q["id"] for q in serialized_questions]
        choice_ids = [c["id"] for q in serialized_questions for c in q["choices"]]

        question_translations = lesson_translation_service.lookup_lesson_translations(
            self.db, "quiz_question", question_ids, normalized, fields=["prompt", "explanation"]
        )
        choice_translations = (
            lesson_translation_service.lookup_lesson_translations(
                self.db, "quiz_choice", choice_ids, normalized, fields=["choice_text"]
            )
            if choice_ids
            else {}
        )

        for question in serialized_questions:
            translated_prompt = question_translations.get((question["id"], "prompt"))
            if translated_prompt is not None:
                question["prompt"] = translated_prompt

            translated_explanation = question_translations.get((question["id"], "explanation"))
            if translated_explanation is not None:
                question["explanation"] = translated_explanation

            for choice in question["choices"]:
                translated_choice_text = choice_translations.get((choice["id"], "choice_text"))
                if translated_choice_text is not None:
                    choice["choice_text"] = translated_choice_text

    @staticmethod
    def _to_utc(value: Optional[datetime]) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def process_quiz_submission_background(
    lesson_content_id: int,
    user_id: str,
    question_id: int,
    selected_choice_id: int,
    answered_at: Optional[datetime] = None,
) -> None:
    """Background-task entry point for fire-and-forget quiz submission handling."""
    db = SessionLocal()
    try:
        service = HikmahQuizService(db)
        service.process_submission(
            lesson_content_id=lesson_content_id,
            user_id=user_id,
            question_id=question_id,
            selected_choice_id=selected_choice_id,
            answered_at=answered_at,
        )
    except Exception:
        db.rollback()
        logger.exception(
            "Unhandled error processing quiz submission in background",
            extra={
                "lesson_content_id": lesson_content_id,
                "question_id": question_id,
                "selected_choice_id": selected_choice_id,
                "user_id": user_id,
            },
        )
    finally:
        db.close()
