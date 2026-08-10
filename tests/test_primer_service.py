"""
Unit tests for PrimerService
"""

import sys
from pathlib import Path

# Add the parent directory to the path so we can import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from sqlalchemy.orm import Session

import services.primer_service as primer_service_module
from services.primer_service import PrimerService
from db.models.lessons import Lesson
from db.models.personalized_primers import PersonalizedPrimer
from agents.models.user_memory_models import UserMemoryProfile


# Mock data fixtures
@pytest.fixture
def mock_db():
    """Create a mock database session"""
    db = Mock(spec=Session)
    db.query = Mock(return_value=Mock())
    db.execute = Mock()
    return db


@pytest.fixture
def mock_embedding_service():
    """Create a mock embedding service"""
    mock_instance = Mock()
    # Default to tag-based fallback (no embeddings)
    mock_instance.has_note_embeddings.return_value = False
    mock_instance.has_lesson_chunks.return_value = False
    mock_instance.find_similar_notes_to_lesson.return_value = []
    mock_instance.calculate_signal_quality.return_value = 0.0
    return mock_instance


@pytest.fixture
def primer_service(mock_db, mock_embedding_service):
    """Create a PrimerService instance with mock db and embedding service"""
    with patch('services.primer_service.EmbeddingService') as mock_emb_class:
        mock_emb_class.return_value = mock_embedding_service
        service = PrimerService(mock_db)
        service.embedding_service = mock_embedding_service
        return service


@pytest.fixture
def sample_lesson():
    """Create a sample lesson object"""
    lesson = Mock(spec=Lesson)
    lesson.id = 1
    lesson.title = "Introduction to Tajweed"
    lesson.summary = "Learn the basic rules of Quranic recitation and pronunciation"
    lesson.tags = ["tajweed", "quran", "recitation", "basics"]
    lesson.baseline_primer_bullets = [
        "This lesson introduces the fundamental rules of Tajweed",
        "You'll learn proper pronunciation of Arabic letters",
        "Practical exercises will help you apply these rules"
    ]
    lesson.updated_at = datetime(2026, 1, 15, 10, 0, 0)
    return lesson


@pytest.fixture
def sample_user_profile():
    """Create a sample user memory profile"""
    profile = Mock(spec=UserMemoryProfile)
    profile.user_id = "user123"
    profile.learning_notes = [
        {
            "id": "note1",
            "content": "User struggles with Arabic letter pronunciation",
            "confidence": 0.8,
            "tags": ["arabic", "pronunciation", "tajweed"],
            "created_at": "2026-01-10T10:00:00"
        },
        {
            "id": "note2",
            "content": "Expressed difficulty understanding Makharij concepts",
            "confidence": 0.7,
            "tags": ["tajweed", "makharij", "basics"],
            "created_at": "2026-01-12T14:00:00"
        }
    ]
    profile.interest_notes = [
        {
            "id": "note3",
            "content": "Very interested in Quranic recitation improvement",
            "confidence": 0.9,
            "tags": ["quran", "recitation", "tajweed"],
            "created_at": "2026-01-11T09:00:00"
        }
    ]
    profile.knowledge_notes = [
        {
            "id": "note4",
            "content": "Has basic knowledge of Arabic alphabet",
            "confidence": 0.6,
            "tags": ["arabic", "basics"],
            "created_at": "2026-01-09T16:00:00"
        }
    ]
    profile.preference_notes = [
        {
            "id": "note5",
            "content": "Prefers practical examples over theory",
            "confidence": 0.8,
            "tags": ["learning_style", "practical"],
            "created_at": "2026-01-08T11:00:00"
        }
    ]
    profile.memory_version = datetime(2026, 1, 18, 14, 0, 0)
    profile.last_significant_update = datetime(2026, 1, 18, 14, 0, 0)
    profile.total_interactions = 15
    return profile


@pytest.fixture
def sample_user_signals():
    """Create sample user signals dict"""
    return {
        "available": True,
        "learning_notes": [
            {
                "id": "note1",
                "content": "User struggles with Arabic letter pronunciation",
                "confidence": 0.8,
                "tags": ["arabic", "pronunciation", "tajweed"]
            },
            {
                "id": "note2",
                "content": "Expressed difficulty understanding Makharij concepts",
                "confidence": 0.7,
                "tags": ["tajweed", "makharij", "basics"]
            }
        ],
        "interest_notes": [
            {
                "id": "note3",
                "content": "Very interested in Quranic recitation improvement",
                "confidence": 0.9,
                "tags": ["quran", "recitation", "tajweed"]
            }
        ],
        "knowledge_notes": [
            {
                "id": "note4",
                "content": "Has basic knowledge of Arabic alphabet",
                "confidence": 0.6,
                "tags": ["arabic", "basics"]
            }
        ],
        "preference_notes": [],
        "memory_version": datetime(2026, 1, 18, 14, 0, 0),
        "total_interactions": 15
    }


# Test: Note Filtering by Tags
class TestNoteFiltering:
    """Test note filtering logic"""

    def test_filter_notes_with_matching_tags(self, primer_service):
        """Test filtering notes that have matching tags"""
        notes = [
            {"id": "1", "content": "Note 1", "tags": ["tajweed", "quran"]},
            {"id": "2", "content": "Note 2", "tags": ["fiqh", "prayer"]},
            {"id": "3", "content": "Note 3", "tags": ["quran", "tafsir"]},
        ]
        lesson_tags = ["quran", "tajweed"]

        result = primer_service._filter_notes_by_tags(notes, lesson_tags)

        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert result[1]["id"] == "3"

    def test_filter_notes_no_matches(self, primer_service):
        """Test filtering when no notes match"""
        notes = [
            {"id": "1", "content": "Note 1", "tags": ["fiqh", "zakat"]},
            {"id": "2", "content": "Note 2", "tags": ["hadith", "sunnah"]},
        ]
        lesson_tags = ["quran", "tajweed"]

        result = primer_service._filter_notes_by_tags(notes, lesson_tags)

        assert len(result) == 0

    def test_filter_notes_empty_lesson_tags(self, primer_service):
        """Test filtering with empty lesson tags"""
        notes = [
            {"id": "1", "content": "Note 1", "tags": ["tajweed"]},
        ]
        lesson_tags = []

        result = primer_service._filter_notes_by_tags(notes, lesson_tags)

        assert len(result) == 0

    def test_filter_notes_empty_notes(self, primer_service):
        """Test filtering with empty notes list"""
        notes = []
        lesson_tags = ["quran", "tajweed"]

        result = primer_service._filter_notes_by_tags(notes, lesson_tags)

        assert len(result) == 0

    def test_filter_notes_missing_tags_field(self, primer_service):
        """Test filtering notes that don't have tags field"""
        notes = [
            {"id": "1", "content": "Note without tags"},
            {"id": "2", "content": "Note 2", "tags": ["quran"]},
        ]
        lesson_tags = ["quran"]

        result = primer_service._filter_notes_by_tags(notes, lesson_tags)

        assert len(result) == 1
        assert result[0]["id"] == "2"


# Test: Signal Quality Assessment
class TestSignalQualityAssessment:
    """Test signal quality scoring logic"""

    def test_assess_quality_unavailable_signals(self, primer_service):
        """Test quality score when signals are unavailable"""
        signals = {"available": False}

        score = primer_service._assess_signal_quality(signals)

        assert score == 0.0

    def test_assess_quality_high_quality_signals(self, primer_service):
        """Test quality score with high-quality signals"""
        signals = {
            "available": True,
            "learning_notes": [{"confidence": 0.8}, {"confidence": 0.9}],
            "interest_notes": [{"confidence": 0.85}],
            "knowledge_notes": [{"confidence": 0.75}],
            "total_interactions": 15
        }

        score = primer_service._assess_signal_quality(signals)

        # Should score: 0.6 (notes >= 3) + 0.2 (interactions >= 10) + 0.2 (high confidence) = 1.0
        assert score == 1.0

    def test_assess_quality_medium_signals(self, primer_service):
        """Test quality score with medium signals"""
        signals = {
            "available": True,
            "learning_notes": [{"confidence": 0.5}],
            "interest_notes": [{"confidence": 0.6}],
            "knowledge_notes": [],
            "total_interactions": 7
        }

        score = primer_service._assess_signal_quality(signals)

        # Should score: 0.3 (notes 1-2) + 0.1 (interactions 5-9) = 0.4
        assert score == 0.4

    def test_assess_quality_low_signals(self, primer_service):
        """Test quality score with low signals"""
        signals = {
            "available": True,
            "learning_notes": [],
            "interest_notes": [],
            "knowledge_notes": [],
            "total_interactions": 2
        }

        score = primer_service._assess_signal_quality(signals)

        # Should score: 0.0 (no notes, few interactions, no high confidence)
        assert score == 0.0

    def test_assess_quality_threshold_boundary(self, primer_service):
        """Test quality score at threshold boundary (0.5)"""
        signals = {
            "available": True,
            "learning_notes": [{"confidence": 0.5}],
            "interest_notes": [{"confidence": 0.6}],
            "knowledge_notes": [{"confidence": 0.55}],
            "total_interactions": 3
        }

        score = primer_service._assess_signal_quality(signals)

        # Should score: 0.6 (notes >= 3) = 0.6 (above threshold)
        assert score >= 0.5


# Test: LLM Response Parsing
class TestLLMResponseParsing:
    """Test LLM response parsing logic"""

    def test_parse_valid_json_response(self, primer_service):
        """Test parsing valid JSON response"""
        response = """
        {
            "personalized_bullets": [
                "First bullet point here",
                "Second bullet point here",
                "Third bullet point here"
            ]
        }
        """

        bullets = primer_service._parse_llm_response(response)

        assert len(bullets) == 3
        assert bullets[0] == "First bullet point here"
        assert bullets[1] == "Second bullet point here"

    def test_parse_json_with_markdown_code_block(self, primer_service):
        """Test parsing JSON wrapped in markdown code block"""
        response = """
        Here's the response:
        ```json
        {
            "personalized_bullets": [
                "Bullet one",
                "Bullet two"
            ]
        }
        ```
        """

        bullets = primer_service._parse_llm_response(response)

        assert len(bullets) == 2
        assert bullets[0] == "Bullet one"

    def test_parse_json_with_generic_code_block(self, primer_service):
        """Test parsing JSON in generic code block"""
        response = """
        ```
        {
            "personalized_bullets": ["Bullet A", "Bullet B"]
        }
        ```
        """

        bullets = primer_service._parse_llm_response(response)

        assert len(bullets) == 2

    def test_parse_invalid_json(self, primer_service):
        """Test parsing invalid JSON returns empty list"""
        response = "This is not valid JSON {broken"

        bullets = primer_service._parse_llm_response(response)

        assert bullets == []

    def test_parse_json_without_bullets_key(self, primer_service):
        """Test parsing JSON without personalized_bullets key"""
        response = '{"other_key": ["value1", "value2"]}'

        bullets = primer_service._parse_llm_response(response)

        assert bullets == []

    def test_parse_json_with_non_list_bullets(self, primer_service):
        """Test parsing when bullets is not a list"""
        response = '{"personalized_bullets": "not a list"}'

        bullets = primer_service._parse_llm_response(response)

        assert bullets == []

    def test_parse_json_with_empty_strings(self, primer_service):
        """Test parsing filters out empty strings"""
        response = """
        {
            "personalized_bullets": [
                "Valid bullet",
                "",
                "   ",
                "Another valid bullet"
            ]
        }
        """

        bullets = primer_service._parse_llm_response(response)

        assert len(bullets) == 2
        assert bullets[0] == "Valid bullet"
        assert bullets[1] == "Another valid bullet"

    def test_parse_json_limits_to_three_bullets(self, primer_service):
        """Test parsing limits output to max 3 bullets"""
        response = """
        {
            "personalized_bullets": [
                "Bullet 1",
                "Bullet 2",
                "Bullet 3",
                "Bullet 4",
                "Bullet 5"
            ]
        }
        """

        bullets = primer_service._parse_llm_response(response)

        assert len(bullets) == 3


# Test: Fetch User Signals
class TestFetchUserSignals:
    """Test fetching and filtering user signals"""

    def test_fetch_signals_no_profile(self, primer_service, mock_db):
        """Test fetching signals when user has no profile"""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        signals = primer_service._fetch_user_signals("user123", lesson_id=1, lesson_tags=["quran"])

        assert signals["available"] is False

    def test_fetch_signals_with_profile_tag_fallback(self, primer_service, mock_db, sample_user_profile):
        """Test fetching signals with valid profile using tag-based fallback"""
        mock_db.query.return_value.filter.return_value.first.return_value = sample_user_profile
        # Embeddings not available, so falls back to tags
        primer_service.embedding_service.has_note_embeddings.return_value = False
        primer_service.embedding_service.has_lesson_chunks.return_value = False

        signals = primer_service._fetch_user_signals("user123", lesson_id=1, lesson_tags=["quran", "tajweed"])

        assert signals["available"] is True
        assert "learning_notes" in signals
        assert "interest_notes" in signals
        assert signals["total_interactions"] == 15
        assert signals["similarity_based"] is False

    def test_fetch_signals_filters_by_tags(self, primer_service, mock_db, sample_user_profile):
        """Test that signals are filtered by lesson tags when using fallback"""
        mock_db.query.return_value.filter.return_value.first.return_value = sample_user_profile
        primer_service.embedding_service.has_note_embeddings.return_value = False
        primer_service.embedding_service.has_lesson_chunks.return_value = False

        signals = primer_service._fetch_user_signals("user123", lesson_id=1, lesson_tags=["tajweed"])

        # Should only include notes with "tajweed" tag
        learning_notes = signals["learning_notes"]
        assert all("tajweed" in note.get("tags", []) for note in learning_notes)

    def test_fetch_signals_with_embeddings(self, primer_service, mock_db, sample_user_profile):
        """Test fetching signals using embeddings when available"""
        mock_db.query.return_value.filter.return_value.first.return_value = sample_user_profile
        # Embeddings are available (note embeddings and lesson chunks)
        primer_service.embedding_service.has_note_embeddings.return_value = True
        primer_service.embedding_service.has_lesson_chunks.return_value = True
        primer_service.embedding_service.find_similar_notes_to_lesson.return_value = [
            ("note1", "learning_notes", 0.85),
            ("note3", "interest_notes", 0.75),
        ]
        primer_service.embedding_service.calculate_signal_quality.return_value = 0.8

        signals = primer_service._fetch_user_signals("user123", lesson_id=1, lesson_tags=["tajweed"])

        assert signals["available"] is True
        assert signals["similarity_based"] is True
        assert "avg_similarity" in signals
        assert "note_similarities" in signals


# Test: Similarity-Based Quality Assessment
class TestSimilarityQualityAssessment:
    """Test similarity-based signal quality scoring"""

    def test_assess_similarity_quality_high(self, primer_service):
        """Test similarity quality with high avg_similarity"""
        signals = {
            "available": True,
            "similarity_based": True,
            "avg_similarity": 0.8,
            "learning_notes": [{"id": "1"}, {"id": "2"}],
            "interest_notes": [{"id": "3"}],
            "knowledge_notes": [],
            "total_interactions": 15
        }

        score = primer_service._assess_similarity_quality(signals)

        # Should score: 0.6 (similarity capped) + 0.2 (3 notes) + 0.2 (interactions) = 1.0
        assert score == 1.0

    def test_assess_similarity_quality_medium(self, primer_service):
        """Test similarity quality with medium avg_similarity"""
        signals = {
            "available": True,
            "similarity_based": True,
            "avg_similarity": 0.5,
            "learning_notes": [{"id": "1"}],
            "interest_notes": [],
            "knowledge_notes": [],
            "total_interactions": 7
        }

        score = primer_service._assess_similarity_quality(signals)

        # Should score: 0.5 (similarity) + 0.1 (1 note) + 0.1 (5-9 interactions) = 0.7
        assert 0.6 <= score <= 0.8

    def test_assess_similarity_quality_low(self, primer_service):
        """Test similarity quality with low avg_similarity"""
        signals = {
            "available": True,
            "similarity_based": True,
            "avg_similarity": 0.2,
            "learning_notes": [],
            "interest_notes": [],
            "knowledge_notes": [],
            "total_interactions": 2
        }

        score = primer_service._assess_similarity_quality(signals)

        # Should score: 0.2 (similarity) + 0 (no notes) + 0 (few interactions) = 0.2
        assert score == 0.2


# Test: Fallback Response
class TestFallbackResponse:
    """Test fallback response format"""

    def test_fallback_response_format(self, primer_service):
        """Test fallback response has correct structure"""
        response = primer_service._fallback_response()

        assert response["personalized_bullets"] == []
        assert response["generated_at"] is None
        assert response["from_cache"] is False
        assert response["stale"] is False
        assert response["personalized_available"] is False


# Test: Pooled connection released before LLM work (Sentry PYTHON-FASTAPI-2E)
class TestPoolReleaseBeforeLLM:
    """The sync pool is capped at size 2 + overflow 1 per worker (DEE-59), so
    holding a session across LLM generation (tens of seconds) starves every
    other sync route. These tests pin the fix: the session must be closed
    before the first LLM token is requested."""

    @pytest.mark.asyncio
    async def test_stream_releases_session_before_llm_stream(
        self, primer_service, mock_db, sample_lesson, sample_user_signals
    ):
        """_stream_bullets_with_llm closes the session before consuming the LLM stream"""
        closed_before_llm = {}

        async def fake_astream(messages):
            closed_before_llm["value"] = mock_db.close.called
            chunk = Mock()
            chunk.content = '{"personalized_bullets": ["Bullet 1", "Bullet 2"]}'
            yield chunk

        with patch.object(primer_service, "_fetch_lesson_content", return_value=[]):
            with patch.object(primer_service_module, "primers_model") as mock_model:
                mock_model.astream = fake_astream
                events = [
                    event
                    async for event in primer_service._stream_bullets_with_llm(
                        sample_lesson, sample_user_signals
                    )
                ]

        assert closed_before_llm["value"] is True
        bullet_events = [e for e in events if e["type"] == "bullet"]
        assert [e["content"] for e in bullet_events] == ["Bullet 1", "Bullet 2"]

    @pytest.mark.asyncio
    async def test_generate_releases_session_before_llm_call(
        self, primer_service, mock_db, sample_lesson, sample_user_signals
    ):
        """_generate_bullets_with_llm closes the session before awaiting the LLM"""
        closed_before_llm = {}

        async def fake_ainvoke(messages):
            closed_before_llm["value"] = mock_db.close.called
            response = Mock()
            response.content = '{"personalized_bullets": ["Bullet 1", "Bullet 2"]}'
            return response

        with patch.object(primer_service, "_fetch_lesson_content", return_value=[]):
            with patch.object(primer_service_module, "primers_model") as mock_model:
                mock_model.ainvoke = fake_ainvoke
                bullets = await primer_service._generate_bullets_with_llm(
                    sample_lesson, sample_user_signals
                )

        assert closed_before_llm["value"] is True
        assert bullets == ["Bullet 1", "Bullet 2"]


# Integration Test: Full Generation Flow
class TestGenerationFlow:
    """Integration tests for full generation flow"""

    @pytest.mark.asyncio
    async def test_generate_with_insufficient_signals(self, primer_service, mock_db, sample_lesson):
        """Test generation returns fallback when signals are insufficient"""
        # Mock lesson retrieval
        with patch('services.primer_service.lesson_crud') as mock_lesson_crud:
            mock_lesson_crud.get.return_value = sample_lesson

            # Mock user profile with low quality signals
            low_quality_profile = Mock(spec=UserMemoryProfile)
            low_quality_profile.learning_notes = []
            low_quality_profile.interest_notes = []
            low_quality_profile.knowledge_notes = []
            low_quality_profile.preference_notes = []
            low_quality_profile.total_interactions = 1
            mock_db.query.return_value.filter.return_value.first.return_value = low_quality_profile

            # Mock cache check (no cache)
            with patch.object(primer_service, '_get_cached_primer', return_value=None):
                result = await primer_service.generate_personalized_primer("user123", 1)

                assert result["personalized_available"] is False
                assert result["personalized_bullets"] == []

    @pytest.mark.asyncio
    async def test_generate_returns_cached_when_fresh(self, primer_service, mock_db, sample_lesson):
        """Test generation returns cached primer when fresh"""
        cached_response = {
            "personalized_bullets": ["Cached bullet 1", "Cached bullet 2"],
            "generated_at": datetime.now(timezone.utc),
            "from_cache": True,
            "stale": False,
            "personalized_available": True
        }

        with patch.object(primer_service, '_get_cached_primer', return_value=cached_response):
            result = await primer_service.generate_personalized_primer("user123", 1, force_refresh=False)

            assert result["from_cache"] is True
            assert len(result["personalized_bullets"]) == 2

    @pytest.mark.asyncio
    async def test_generate_bypasses_cache_with_force_refresh(self, primer_service, mock_db, sample_lesson, sample_user_profile):
        """Test generation bypasses cache when force_refresh is True"""
        with patch('services.primer_service.lesson_crud') as mock_lesson_crud:
            mock_lesson_crud.get.return_value = sample_lesson
            mock_db.query.return_value.filter.return_value.first.return_value = sample_user_profile

            # Mock LLM generation
            mock_llm_response = Mock()
            mock_llm_response.content = '{"personalized_bullets": ["New bullet 1", "New bullet 2"]}'

            with patch('services.primer_service.small_llm') as mock_llm:
                mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)

                # Mock cache methods
                with patch.object(primer_service, '_get_cached_primer', return_value=None):
                    with patch.object(primer_service, '_cache_primer'):
                        result = await primer_service.generate_personalized_primer("user123", 1, force_refresh=True)

                        # Should have called LLM (not used cache)
                        assert result["from_cache"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
