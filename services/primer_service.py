"""
Service layer for personalized lesson primers generation and management.

Uses embeddings-based similarity search for note relevance (with tag-based fallback).
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import json
import logging
import time

from sqlalchemy.orm import Session

from core.chat_models import get_enhancer_model
from core.config import NOTE_FILTER_THRESHOLD, SIGNAL_QUALITY_THRESHOLD
from core.prompt_templates import primer_generation_messages
from db.crud.personalized_primers import personalized_primer_crud
from db.models.lesson_content import LessonContent
from db.utils.personalized_primers_utils import (
    is_primer_fresh,
    compute_inputs_hash,
    calculate_ttl_expiration,
    get_ttl_bucket
)
from db.schemas.personalized_primers import PersonalizedPrimerCreate, PersonalizedPrimerUpdate
from agents.models.user_memory_models import UserMemoryProfile
from services.embedding_service import EmbeddingService
from core.config import SIGNAL_QUALITY_THRESHOLD    

logger = logging.getLogger(__name__)

# load model here if needed globally
primers_model = get_enhancer_model()

class PrimerService:
    """
    Service for generating and managing personalized lesson primers.

    Handles:
    - Fetching user signals from memory profiles (using embeddings or tag-based fallback)
    - Assessing signal quality for personalization
    - Generating personalized bullets via LLM
    - Caching and freshness validation
    """

    def __init__(self, db: Session):
        self.db = db
        self.embedding_service = EmbeddingService(db)

    async def stream_personalized_primer(
        self,
        user_id: str,
        lesson_id: int,
        force_refresh: bool = False,
        filter: bool = False
    ):
        """
        Stream personalized primer generation with real-time updates.

        Yields events:
            {"type": "status", "message": str}
            {"type": "bullet", "index": int, "content": str}
            {"type": "metadata", "from_cache": bool, "generated_at": datetime, ...}
        """
        start_time = time.perf_counter()

        try:
            # Check cache first (unless force_refresh)
            if not force_refresh:
                yield {"type": "status", "message": "Checking cache..."}

                cached_result = self._get_cached_primer(user_id, lesson_id)

                if cached_result:
                    # Send cached bullets one by one
                    yield {"type": "status", "message": "Retrieved from cache"}

                    for idx, bullet in enumerate(cached_result.get("personalized_bullets", [])):
                        yield {
                            "type": "bullet",
                            "index": idx,
                            "content": bullet
                        }

                    # Send metadata
                    yield {
                        "type": "metadata",
                        "from_cache": True,
                        "generated_at": cached_result.get("generated_at").isoformat() if cached_result.get("generated_at") else None,
                        "stale": False,
                        "personalized_available": True
                    }

                    total_duration = time.perf_counter() - start_time
                    logger.info(f"⏱️ [TOTAL] {total_duration:.3f}s (cache hit)")
                    return

            # Generate new primer with streaming
            yield {"type": "status", "message": "Generating personalized primer..."}

            async for event in self._stream_new_primer(user_id, lesson_id, filter):
                yield event

            total_duration = time.perf_counter() - start_time
            logger.info(f"⏱️ [TOTAL] {total_duration:.3f}s")

        except Exception as e:
            total_duration = time.perf_counter() - start_time
            logger.error(f"Error in streaming | Duration: {total_duration:.3f}s | error={str(e)}")

            yield {
                "type": "error",
                "message": str(e),
                "personalized_available": False
            }

    async def _stream_new_primer(self, user_id: str, lesson_id: int, filter: bool = False):
        """Generate and stream a new personalized primer"""
        from db.crud.lessons import lesson_crud

        # Fetch lesson
        yield {"type": "status", "message": "Fetching lesson details..."}
        db_start = time.perf_counter()
        lesson = lesson_crud.get(self.db, lesson_id)

        if not lesson:
            logger.error(f"Lesson not found | lesson_id={lesson_id}")
            yield {
                "type": "metadata",
                "from_cache": False,
                "generated_at": None,
                "stale": False,
                "personalized_available": False
            }
            return

        # Fetch user signals
        yield {"type": "status", "message": "Analyzing your learning history..."}
        user_signals = self._fetch_user_signals(
            user_id=user_id,
            lesson_id=lesson_id,
            lesson_tags=lesson.tags or [],
            filter=filter
        )
        db_duration = time.perf_counter() - db_start
        logger.info(f"[DB] {db_duration:.3f}s")

        # Signal quality check (only when filtering is enabled)
        if filter:
            yield {"type": "status", "message": "Evaluating personalization potential..."}
            signal_quality = self._assess_signal_quality(user_signals)
            threshold = SIGNAL_QUALITY_THRESHOLD if user_signals.get("similarity_based") else 0.5

            if signal_quality < threshold:
                yield {
                    "type": "metadata",
                    "from_cache": False,
                    "generated_at": None,
                    "stale": False,
                    "personalized_available": False
                }
                return

        # Generate bullets with streaming LLM
        yield {"type": "status", "message": "Generating personalized content..."}

        generated_bullets = []

        async for chunk_event in self._stream_bullets_with_llm(lesson, user_signals):
            event_type = chunk_event.get("type")

            if event_type == "llm_chunk":
                yield {
                    "type": "llm_chunk",
                    "content": chunk_event.get("content")
                }
            elif event_type == "bullet":
                bullet_content = chunk_event.get("content")
                bullet_index = chunk_event.get("index")
                generated_bullets.append(bullet_content)

                yield {
                    "type": "bullet",
                    "index": bullet_index,
                    "content": bullet_content
                }

        if not generated_bullets or len(generated_bullets) < 2:
            logger.warning("LLM generation failed or returned insufficient bullets")
            yield {
                "type": "metadata",
                "from_cache": False,
                "generated_at": None,
                "stale": False,
                "personalized_available": False
            }
            return

        # Cache the primer
        yield {"type": "status", "message": "Saving for future use..."}
        cache_start = time.perf_counter()
        self._cache_primer(
            user_id=user_id,
            lesson_id=lesson_id,
            lesson=lesson,
            bullets=generated_bullets,
            user_signals=user_signals
        )
        cache_duration = time.perf_counter() - cache_start
        logger.info(f"[CACHE] {cache_duration:.3f}s")

        # Send final metadata
        generated_at = datetime.now(timezone.utc)
        yield {
            "type": "metadata",
            "from_cache": False,
            "generated_at": generated_at.isoformat(),
            "stale": False,
            "personalized_available": True
        }

    async def generate_personalized_primer(
        self,
        user_id: str,
        lesson_id: int,
        force_refresh: bool = False,
        filter: bool = False
    ) -> Dict[str, Any]:
        """
        Main entry point for primer generation.

        Returns:
            {
                "personalized_bullets": List[str],
                "generated_at": datetime | None,
                "from_cache": bool,
                "stale": bool,
                "personalized_available": bool
            }
        """
        start_time = time.perf_counter()

        try:
            # Check cache first (unless force_refresh)
            if not force_refresh:
                cached_result = self._get_cached_primer(user_id, lesson_id)

                if cached_result:
                    total_duration = time.perf_counter() - start_time
                    logger.info(f"⏱️ [TOTAL] {total_duration:.3f}s (cache hit)")
                    return cached_result

            # Generate new primer
            result = await self._generate_new_primer(user_id, lesson_id, filter)

            total_duration = time.perf_counter() - start_time
            logger.info(f"⏱️ [TOTAL] {total_duration:.3f}s")
            return result

        except Exception as e:
            total_duration = time.perf_counter() - start_time
            logger.error(f"Error | Duration: {total_duration:.3f}s | error={str(e)}")
            return self._fallback_response()

    def _get_cached_primer(
        self,
        user_id: str,
        lesson_id: int
    ) -> Optional[Dict[str, Any]]:
        """Check if a fresh cached primer exists"""
        from db.crud.lessons import lesson_crud

        # Get cached primer
        primer = personalized_primer_crud.get_by_user_and_lesson(
            self.db, user_id, lesson_id
        )

        if not primer:
            return None

        # Get lesson and user memory version
        lesson = lesson_crud.get(self.db, lesson_id)
        if not lesson:
            return None

        user_memory_version = self._get_memory_version(user_id)

        # Check freshness
        if is_primer_fresh(primer, lesson, user_memory_version):
            return {
                "personalized_bullets": primer.personalized_bullets,
                "generated_at": primer.generated_at,
                "from_cache": True,
                "stale": False,
                "personalized_available": True
            }

        return None

    async def _generate_new_primer(
        self,
        user_id: str,
        lesson_id: int,
        filter: bool = False
    ) -> Dict[str, Any]:
        """Generate a new personalized primer"""
        from db.crud.lessons import lesson_crud

        # Fetch lesson and user signals
        db_start = time.perf_counter()
        lesson = lesson_crud.get(self.db, lesson_id)

        if not lesson:
            logger.error(f"Lesson not found | lesson_id={lesson_id}")
            return self._fallback_response()

        # Fetch user signals
        user_signals = self._fetch_user_signals(
            user_id=user_id,
            lesson_id=lesson_id,
            lesson_tags=lesson.tags or [],
            filter=filter
        )
        db_duration = time.perf_counter() - db_start
        logger.info(f"[DB] {db_duration:.3f}s")

        # Signal quality check (only when filtering is enabled)
        if filter:
            signal_quality = self._assess_signal_quality(user_signals)
            threshold = SIGNAL_QUALITY_THRESHOLD if user_signals.get("similarity_based") else 0.5

            if signal_quality < threshold:
                return self._fallback_response()

        # Generate bullets with LLM
        llm_start = time.perf_counter()
        personalized_bullets = await self._generate_bullets_with_llm(
            lesson=lesson,
            user_signals=user_signals
        )
        llm_duration = time.perf_counter() - llm_start
        logger.info(f"[LLM] {llm_duration:.3f}s")

        if not personalized_bullets or len(personalized_bullets) < 2:
            logger.warning(f"LLM generation failed or returned insufficient bullets")
            return self._fallback_response()

        # Cache the primer
        cache_start = time.perf_counter()
        self._cache_primer(
            user_id=user_id,
            lesson_id=lesson_id,
            lesson=lesson,
            bullets=personalized_bullets,
            user_signals=user_signals
        )
        cache_duration = time.perf_counter() - cache_start
        logger.info(f"[CACHE] {cache_duration:.3f}s")

        return {
            "personalized_bullets": personalized_bullets,
            "generated_at": datetime.now(timezone.utc),
            "from_cache": False,
            "stale": False,
            "personalized_available": True
        }

    def _fetch_user_signals(
        self,
        user_id: str,
        lesson_id: int,
        lesson_tags: List[str],
        filter: bool = False
    ) -> Dict[str, Any]:
        """
        Fetch user memory notes with optional filtering.

        Args:
            user_id: User identifier
            lesson_id: Lesson identifier (for embedding lookup)
            lesson_tags: Lesson tags (for fallback)
            filter: If True, use embeddings-based filtering. If False, use all notes.

        Returns:
            Dictionary with user signals
        """
        # Fetch user memory profile
        profile = self.db.query(UserMemoryProfile).filter(
            UserMemoryProfile.user_id == user_id
        ).first()

        if not profile:
            logger.warning(f"No user memory profile found | user_id={user_id}")
            return {"available": False}

        # Use filtering logic if filter=True
        if filter:
            # Check if embeddings exist for both user and lesson
            has_embeddings = (
                self.embedding_service.has_note_embeddings(user_id) and
                self.embedding_service.has_lesson_chunks(lesson_id)
            )

            if has_embeddings:
                # Use embeddings-based similarity search
                embedding_start = time.perf_counter()
                result = self._fetch_signals_with_embeddings(
                    user_id=user_id,
                    lesson_id=lesson_id,
                    profile=profile
                )
                embedding_duration = time.perf_counter() - embedding_start
                logger.info(f"[EMBEDDINGS] {embedding_duration:.3f}s")
                return result
            else:
                # Fallback to tag-based filtering
                result = self._fetch_signals_with_tags(
                    profile=profile,
                    lesson_tags=lesson_tags
                )
                return result

        # Return ALL notes without filtering (filter=False)
        return {
            "available": True,
            "learning_notes": profile.learning_notes or [],
            "interest_notes": profile.interest_notes or [],
            "knowledge_notes": profile.knowledge_notes or [],
            "preference_notes": profile.preference_notes or [],
            "memory_version": profile.last_significant_update,
            "total_interactions": profile.total_interactions,
            "similarity_based": False,  # Not using embeddings
            "avg_similarity": None,
            "note_similarities": {}
        }

    def _fetch_signals_with_embeddings(
        self,
        user_id: str,
        lesson_id: int,
        profile: UserMemoryProfile
    ) -> Dict[str, Any]:
        """
        Fetch user signals using embeddings-based similarity search.

        Compares each user note against all lesson chunks. Notes with max
        similarity >= NOTE_FILTER_THRESHOLD (0.6) are included.
        """
        # Find similar notes by comparing against all lesson chunks
        similar_notes = self.embedding_service.find_similar_notes_to_lesson(
            user_id=user_id,
            lesson_id=lesson_id,
            threshold=NOTE_FILTER_THRESHOLD
        )

        # Build note ID to similarity score mapping
        note_similarities = {note_id: score for note_id, _, score in similar_notes}

        # Retrieve actual note content from profile
        relevant_learning_notes = self._get_notes_by_ids(
            profile.learning_notes or [], note_similarities
        )
        relevant_interest_notes = self._get_notes_by_ids(
            profile.interest_notes or [], note_similarities
        )
        relevant_knowledge_notes = self._get_notes_by_ids(
            profile.knowledge_notes or [], note_similarities
        )
        relevant_preference_notes = self._get_notes_by_ids(
            profile.preference_notes or [], note_similarities
        )

        # Calculate signal quality as average of filtered notes' scores
        avg_similarity = self.embedding_service.calculate_signal_quality(similar_notes)

        return {
            "available": True,
            "learning_notes": relevant_learning_notes,
            "interest_notes": relevant_interest_notes,
            "knowledge_notes": relevant_knowledge_notes,
            "preference_notes": relevant_preference_notes,
            "memory_version": profile.last_significant_update,
            "total_interactions": profile.total_interactions,
            "similarity_based": True,
            "avg_similarity": avg_similarity,
            "note_similarities": note_similarities
        }

    def _get_notes_by_ids(
        self,
        notes: List[Dict],
        note_similarities: Dict[str, float]
    ) -> List[Dict]:
        """
        Get notes that match the IDs in note_similarities.
        Adds similarity_score to each matched note.
        """
        matched_notes = []
        for note in notes:
            note_id = note.get("id")
            if note_id in note_similarities:
                note_with_score = dict(note)
                note_with_score["similarity_score"] = note_similarities[note_id]
                matched_notes.append(note_with_score)

        # Sort by similarity score (highest first)
        matched_notes.sort(key=lambda x: x.get("similarity_score", 0), reverse=True)
        return matched_notes

    def _fetch_signals_with_tags(
        self,
        profile: UserMemoryProfile,
        lesson_tags: List[str]
    ) -> Dict[str, Any]:
        """
        Fallback: Fetch user signals using tag-based filtering.
        Original rule-based implementation.
        """
        relevant_learning_notes = self._filter_notes_by_tags(
            profile.learning_notes or [], lesson_tags
        )
        relevant_interest_notes = self._filter_notes_by_tags(
            profile.interest_notes or [], lesson_tags
        )
        relevant_knowledge_notes = self._filter_notes_by_tags(
            profile.knowledge_notes or [], lesson_tags
        )
        relevant_preference_notes = self._filter_notes_by_tags(
            profile.preference_notes or [], lesson_tags
        )

        return {
            "available": True,
            "learning_notes": relevant_learning_notes,
            "interest_notes": relevant_interest_notes,
            "knowledge_notes": relevant_knowledge_notes,
            "preference_notes": relevant_preference_notes,
            "memory_version": profile.last_significant_update,
            "total_interactions": profile.total_interactions,
            "similarity_based": False,
            "avg_similarity": None,
            "note_similarities": {}
        }

    def _filter_notes_by_tags(
        self,
        notes: List[Dict],
        lesson_tags: List[str]
    ) -> List[Dict]:
        """
        Filter notes that have overlapping tags with the lesson.
        (Original implementation - kept for fallback)
        """
        if not notes or not lesson_tags:
            return []

        relevant = []
        for note in notes:
            note_tags = note.get("tags", [])
            if any(tag in note_tags for tag in lesson_tags):
                relevant.append(note)

        return relevant

    def _assess_signal_quality(self, signals: Dict[str, Any]) -> float:
        """
        Determine if signals are strong enough for personalization.

        Uses similarity-based scoring when available, falls back to
        rule-based scoring.

        Returns quality score from 0.0 to 1.0.
        Threshold: 0.6 (similarity-based) or 0.5 (rule-based)
        """
        if not signals.get("available"):
            return 0.0

        # Embeddings-based quality assessment
        if signals.get("similarity_based"):
            print("Assessing similarity-based signal quality.")
            return self._assess_similarity_quality(signals)

        # Fallback: Rule-based quality assessment
        print("Assessing rule-based signal quality.")
        return self._assess_rule_based_quality(signals)

    def _assess_similarity_quality(self, signals: Dict[str, Any]) -> float:
        """
        Assess signal quality using embedding similarity scores.

        Quality is based on:
        - Average similarity of found notes
        - Number of similar notes found
        - Interaction count
        """
        avg_similarity = signals.get("avg_similarity", 0.0)

        # Count total relevant notes
        total_notes = (
            len(signals.get("learning_notes", [])) +
            len(signals.get("interest_notes", [])) +
            len(signals.get("knowledge_notes", []))
        )
        # Base score from average similarity (max 0.6)
        similarity_score = min(avg_similarity, SIGNAL_QUALITY_THRESHOLD)

        # Bonus for having multiple relevant notes (max 0.2)
        # note_bonus = 0.0
        # if total_notes >= 3:
        #     note_bonus = 0.2
        # elif total_notes >= 1:
        #     note_bonus = 0.1

        # Bonus for interaction history (max 0.2)
        # interactions = signals.get("total_interactions", 0)
        # interaction_bonus = 0.0
        # if interactions >= 10:
        #     interaction_bonus = 0.2
        # elif interactions >= 5:
        #     interaction_bonus = 0.1

        # total_score = similarity_score + note_bonus + interaction_bonus

        # logger.debug(
        #     f"Similarity quality assessment | avg_sim={avg_similarity:.3f} | "
        #     f"notes={total_notes} | interactions={interactions} | "
            # f"total_score={total_score:.3f}"
        # )
        print("\"Avg Sim:", similarity_score, "\n\n")
        # return min(total_score, 1.0)
        return similarity_score

    def _assess_rule_based_quality(self, signals: Dict[str, Any]) -> float:
        """
        Original rule-based quality assessment (fallback).
        """
        score = 0.0

        # Check for relevant notes (max 0.6)
        total_notes = (
            len(signals.get("learning_notes", [])) +
            len(signals.get("interest_notes", [])) +
            len(signals.get("knowledge_notes", []))
        )

        if total_notes >= 3:
            score += 0.6
        elif total_notes >= 1:
            score += 0.3

        # Check interaction count (max 0.2)
        interactions = signals.get("total_interactions", 0)
        if interactions >= 10:
            score += 0.2
        elif interactions >= 5:
            score += 0.1

        # Check note confidence (max 0.2)
        has_high_confidence = any(
            note.get("confidence", 0) >= 0.7
            for note in (
                signals.get("learning_notes", []) +
                signals.get("interest_notes", []) +
                signals.get("knowledge_notes", [])
            )
        )
        if has_high_confidence:
            score += 0.2

        return min(score, 1.0)

    def _fetch_lesson_content(self, lesson_id: int) -> List[Dict[str, str]]:
        """
        Fetch all lesson content pages for a lesson, ordered by position.

        Returns:
            List of dicts with 'title' and 'content_body' for each page
        """
        content_rows = (
            self.db.query(LessonContent)
            .filter(LessonContent.lesson_id == lesson_id)
            .order_by(LessonContent.order_position)
            .all()
        )

        return [
            {
                "title": row.title or "",
                "content_body": row.content_body or ""
            }
            for row in content_rows
        ]

    def _format_lesson_content(self, content_pages: List[Dict[str, str]]) -> str:
        """
        Format lesson content pages into a single string for LLM context.

        Args:
            content_pages: List of dicts with 'title' and 'content_body'

        Returns:
            Formatted string with all pages
        """
        if not content_pages:
            return "No lesson content available"

        formatted_sections = []
        for i, page in enumerate(content_pages, 1):
            section = f"--- Page {i}: {page['title']} ---\n{page['content_body']}"
            formatted_sections.append(section)

        return "\n\n".join(formatted_sections)

    async def _generate_bullets_with_llm(
        self,
        lesson: Any,
        user_signals: Dict[str, Any]
    ) -> List[str]:
        """Call LLM to generate personalized bullets"""

        # Format baseline bullets
        baseline_bullets = "\n".join([
            f"• {bullet}" for bullet in (lesson.baseline_primer_bullets or [])
        ])

        # Fetch and format lesson content from lesson_content table
        content_pages = self._fetch_lesson_content(lesson.id)
        lesson_content = self._format_lesson_content(content_pages)

        # Format user notes
        def format_notes(notes: List[Dict]) -> str:
            if not notes:
                return "None available"
            return "\n".join([
                f"- {note.get('content', '')} (confidence: {note.get('confidence', 0):.2f})"
                for note in notes  # Using ALL notes (no limit)
            ])

        # Prepare formatted user notes
        user_learning_notes = format_notes(user_signals.get("learning_notes", []))
        user_interest_notes = format_notes(user_signals.get("interest_notes", []))
        user_knowledge_notes = format_notes(user_signals.get("knowledge_notes", []))
        user_preference_notes = format_notes(user_signals.get("preference_notes", []))

        # Prepare prompt inputs
        prompt_inputs = {
            "lesson_title": lesson.title,
            "lesson_content": lesson_content,
            "baseline_bullets": baseline_bullets or "No baseline bullets available",
            "user_learning_notes": user_learning_notes,
            "user_interest_notes": user_interest_notes,
            "user_knowledge_notes": user_knowledge_notes,
            "user_preference_notes": user_preference_notes,
        }

        # Log all prompt inputs for visibility
        print("\n" + "=" * 80)
        print("PRIMER GENERATION - PROMPT INPUTS")
        print("=" * 80)

        print(f"\n[v] LESSON TITLE: {lesson.title}")

        print(f"\n[v] LESSON CONTENT PAGES: {len(content_pages)} pages fetched")
        for i, page in enumerate(content_pages, 1):
            title_preview = page['title'][:50] + "..." if len(page['title']) > 50 else page['title']
            content_len = len(page['content_body'])
            print(f"    Page {i}: {title_preview} ({content_len} chars)")

        print(f"\n[v] BASELINE BULLETS: {len(lesson.baseline_primer_bullets or [])} bullets")
        for i, bullet in enumerate(lesson.baseline_primer_bullets or [], 1):
            bullet_preview = bullet[:80] + "..." if len(bullet) > 80 else bullet
            print(f"    {i}. {bullet_preview}")

        print(f"\n[v] USER LEARNING NOTES (weak points):")
        print(f"    {user_learning_notes}")

        print(f"\n[v] USER INTEREST NOTES:")
        print(f"    {user_interest_notes}")

        print(f"\n[v] USER KNOWLEDGE NOTES:")
        print(f"    {user_knowledge_notes}")

        print(f"\n[v] USER PREFERENCE NOTES:")
        print(f"    {user_preference_notes}")

        print("\n" + "-" * 80)
        print("Generating personalized primers with LLM...")
        print("-" * 80)

        # Generate with LLM
        messages = primer_generation_messages(**prompt_inputs)
        # All DB reads for this generation are done. Release the pooled
        # connection before the long LLM call so concurrent primer requests
        # don't starve the size-2+1 sync pool (same rule as the hikmah quiz
        # memory path in services/hikmah_quiz_service.py). The session stays
        # usable — _cache_primer re-acquires a connection for the short write.
        self.db.close()
        # model = get_enhancer_model()
        # response = await model.ainvoke(messages)
        response = await primers_model.ainvoke(messages)
        # Parse response
        bullets = self._parse_llm_response(response.content)

        # Log generated output
        print("\n[v] LLM RESPONSE RECEIVED")
        print(f"\n[v] GENERATED PERSONALIZED BULLETS: {len(bullets)} bullets")
        for i, bullet in enumerate(bullets, 1):
            # bullet_preview = bullet[:100] + "..." if len(bullet) > 100 else bullet
            print(f"    {i}. {bullet}")

        print("\n" + "=" * 80)
        print("PRIMER GENERATION COMPLETE")
        print("=" * 80 + "\n")

        return bullets

    async def _stream_bullets_with_llm(
        self,
        lesson: Any,
        user_signals: Dict[str, Any]
    ):
        """
        Stream LLM generation of personalized bullets in real-time.

        Yields:
            {"type": "llm_chunk", "content": str} - Raw LLM tokens as they arrive
            {"type": "bullet", "index": int, "content": str} - Parsed bullets after completion
        """
        # Format baseline bullets
        baseline_bullets = "\n".join([
            f"• {bullet}" for bullet in (lesson.baseline_primer_bullets or [])
        ])

        # Fetch and format lesson content
        content_pages = self._fetch_lesson_content(lesson.id)
        lesson_content = self._format_lesson_content(content_pages)

        # Format user notes
        def format_notes(notes: List[Dict]) -> str:
            if not notes:
                return "None available"
            return "\n".join([
                f"- {note.get('content', '')} (confidence: {note.get('confidence', 0):.2f})"
                for note in notes  # Using ALL notes (no limit)
            ])

        user_learning_notes = format_notes(user_signals.get("learning_notes", []))
        user_interest_notes = format_notes(user_signals.get("interest_notes", []))
        user_knowledge_notes = format_notes(user_signals.get("knowledge_notes", []))
        user_preference_notes = format_notes(user_signals.get("preference_notes", []))

        # Prepare prompt
        prompt_inputs = {
            "lesson_title": lesson.title,
            "lesson_content": lesson_content,
            "baseline_bullets": baseline_bullets or "No baseline bullets available",
            "user_learning_notes": user_learning_notes,
            "user_interest_notes": user_interest_notes,
            "user_knowledge_notes": user_knowledge_notes,
            "user_preference_notes": user_preference_notes,
        }

        # Generate with streaming LLM - stream tokens in real-time
        messages = primer_generation_messages(**prompt_inputs)
        # All DB reads for this generation are done. Release the pooled
        # connection before the LLM stream (tens of seconds) so concurrent
        # primer streams don't pin the entire size-2+1 sync pool and starve
        # other sync routes (hikmah trees, quiz-submit). The session stays
        # usable — _cache_primer re-acquires a connection for the short write.
        self.db.close()
        # model = get_enhancer_model()

        # Stream the response and send chunks immediately
        accumulated_content = ""
        first_token_received = False
        llm_start_time = time.perf_counter()

        # async for chunk in model.astream(messages):
        async for chunk in primers_model.astream(messages):
            if hasattr(chunk, 'content') and chunk.content:
                # Log first token timing
                if not first_token_received:
                    first_token_time = time.perf_counter() - llm_start_time
                    logger.info(f"[FIRST TOKEN] {first_token_time:.3f}s")
                    first_token_received = True

                accumulated_content += chunk.content
                # Yield the chunk immediately for real-time streaming
                yield {
                    "type": "llm_chunk",
                    "content": chunk.content
                }

        llm_total_time = time.perf_counter() - llm_start_time
        logger.info(f"[LLM] {llm_total_time:.3f}s")

        # Parse the complete response
        bullets = self._parse_llm_response(accumulated_content)

        # Yield each parsed bullet
        for idx, bullet in enumerate(bullets):
            yield {
                "type": "bullet",
                "index": idx,
                "content": bullet
            }

    def _parse_llm_response(self, response_content: str) -> List[str]:
        """Parse LLM response to extract bullets"""
        try:
            # Try to extract JSON from response
            # Handle markdown code blocks
            content = response_content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            # Parse JSON
            data = json.loads(content)
            bullets = data.get("personalized_bullets", [])

            # Validate bullets
            if not isinstance(bullets, list):
                logger.error("Bullets is not a list")
                return []

            # Filter valid bullets (non-empty strings)
            valid_bullets = [
                bullet.strip() for bullet in bullets
                if isinstance(bullet, str) and bullet.strip()
            ]

            return valid_bullets[:3]  # Max 3 bullets

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")
            return []

    def _cache_primer(
        self,
        user_id: str,
        lesson_id: int,
        lesson: Any,
        bullets: List[str],
        user_signals: Dict[str, Any]
    ) -> None:
        """Store generated primer in database"""
        now = datetime.now(timezone.utc)

        # Compute inputs hash
        note_ids = [
            note.get("id", "") for note in (
                user_signals.get("learning_notes", []) +
                user_signals.get("interest_notes", []) +
                user_signals.get("knowledge_notes", [])
            )
        ]

        inputs_hash = compute_inputs_hash(
            lesson_summary=lesson.summary or "",
            lesson_tags=lesson.tags or [],
            note_ids=note_ids,
            ttl_bucket=get_ttl_bucket(now)
        )

        # Calculate TTL expiration
        ttl_expires_at = calculate_ttl_expiration(now, ttl_days=5)

        # Check if primer already exists
        existing_primer = personalized_primer_crud.get_by_user_and_lesson(
            self.db, user_id, lesson_id
        )

        if existing_primer:
            # Update existing primer
            primer_update = PersonalizedPrimerUpdate(
                personalized_bullets=bullets,
                generated_at=now,
                inputs_hash=inputs_hash,
                lesson_version=lesson.updated_at or now,
                memory_version=user_signals.get("memory_version", now),
                ttl_expires_at=ttl_expires_at,
                stale=False
            )
            personalized_primer_crud.update(self.db, existing_primer, primer_update)
        else:
            # Create new primer
            primer_create = PersonalizedPrimerCreate(
                user_id=user_id,
                lesson_id=lesson_id,
                personalized_bullets=bullets,
                generated_at=now,
                inputs_hash=inputs_hash,
                lesson_version=lesson.updated_at or now,
                memory_version=user_signals.get("memory_version", now),
                ttl_expires_at=ttl_expires_at,
                stale=False
            )
            personalized_primer_crud.create(self.db, primer_create)

    def _get_memory_version(self, user_id: str) -> Optional[datetime]:
        """Get user's memory version timestamp"""
        profile = self.db.query(UserMemoryProfile).filter(
            UserMemoryProfile.user_id == user_id
        ).first()
        # Use last_significant_update as the memory version timestamp
        # (memory_version field is an Integer counter, not a timestamp)
        if profile and profile.last_significant_update:
            # Ensure timezone-aware datetime for comparison with other timestamps
            if profile.last_significant_update.tzinfo is None:
                return profile.last_significant_update.replace(tzinfo=timezone.utc)
            return profile.last_significant_update
        return None

    def _fallback_response(self) -> Dict[str, Any]:
        """Return fallback response when personalization is not available"""
        return {
            "personalized_bullets": [],
            "generated_at": None,
            "from_cache": False,
            "stale": False,
            "personalized_available": False
        }
