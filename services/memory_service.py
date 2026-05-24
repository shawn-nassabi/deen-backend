from datetime import datetime
from typing import Dict, List, Optional
import uuid
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.repositories.memory_profile_repository import MemoryProfileRepository
from db.repositories.memory_event_repository import MemoryEventRepository
from agents.models.user_memory_models import UserMemoryProfile, MemoryEvent

logger = logging.getLogger(__name__)


class MemoryService:
    """
    Coordinates memory profile and event persistence.
    Keeps commit/rollback control in the service/agent layer.
    """

    def __init__(
        self,
        db: Session,
        profile_repo: Optional[MemoryProfileRepository] = None,
        event_repo: Optional[MemoryEventRepository] = None,
    ):
        self.db = db
        self.profile_repo = profile_repo or MemoryProfileRepository()
        self.event_repo = event_repo or MemoryEventRepository()

    def get_or_create_profile(self, user_id: str) -> UserMemoryProfile:
        profile = self.profile_repo.get_by_user_id(self.db, user_id)
        if profile:
            return profile
        # Savepoint protects the outer transaction from a unique-violation
        # raised by a concurrent get_or_create for the same user_id. On
        # IntegrityError the savepoint rolls back, the outer session stays
        # usable, and we re-fetch the row the race winner just inserted.
        try:
            with self.db.begin_nested():
                profile = self.profile_repo.create(
                    self.db,
                    user_id=user_id,
                    defaults={
                        "learning_notes": [],
                        "interest_notes": [],
                        "knowledge_notes": [],
                        "behavior_notes": [],
                        "preference_notes": [],
                    },
                )
                # No outer commit here; caller controls commit boundary.
                self.db.flush()
            return profile
        except IntegrityError:
            existing = self.profile_repo.get_by_user_id(self.db, user_id)
            if existing is None:
                # IntegrityError came from something other than the
                # uq_user_memory_profiles_user_id race — re-raise.
                raise
            return existing

    def add_notes(self, profile: UserMemoryProfile, new_notes: List[Dict]) -> UserMemoryProfile:
        # Stamp notes
        stamped_notes = []
        for note in new_notes:
            note_copy = dict(note)
            note_copy["id"] = note_copy.get("id") or str(uuid.uuid4())
            note_copy["created_at"] = note_copy.get("created_at") or datetime.utcnow().isoformat()
            stamped_notes.append(note_copy)

        # Build updated lists
        learning_notes = (profile.learning_notes or []).copy()
        knowledge_notes = (profile.knowledge_notes or []).copy()
        interest_notes = (profile.interest_notes or []).copy()
        behavior_notes = (profile.behavior_notes or []).copy()
        preference_notes = (profile.preference_notes or []).copy()

        for note in stamped_notes:
            note_type = note.get("note_type", "learning_notes")
            if note_type == "learning_notes":
                learning_notes.append(note)
            elif note_type == "knowledge_notes":
                knowledge_notes.append(note)
            elif note_type == "interest_notes":
                interest_notes.append(note)
            elif note_type == "behavior_notes":
                behavior_notes.append(note)
            elif note_type == "preference_notes":
                preference_notes.append(note)

        self.profile_repo.update_note_lists(
            self.db,
            profile,
            learning_notes=learning_notes,
            knowledge_notes=knowledge_notes,
            interest_notes=interest_notes,
            behavior_notes=behavior_notes,
            preference_notes=preference_notes,
        )

        # Metadata updates
        profile.total_interactions += 1
        now = datetime.utcnow()
        self.profile_repo.touch_metadata(
            self.db,
            profile,
            last_significant_update=now,
            updated_at=now,
        )

        # Generate embeddings for new notes
        self._generate_note_embeddings(profile.user_id, stamped_notes)

        return profile

    def _generate_note_embeddings(self, user_id: str, notes: List[Dict]) -> None:
        """
        Generate and store embeddings for newly added notes.
        This is a non-blocking operation - failures are logged but don't affect note storage.
        """
        if not notes:
            return

        try:
            from services.embedding_service import EmbeddingService

            embedding_service = EmbeddingService(self.db)

            # Group notes by type for batch processing
            notes_by_type: Dict[str, List[Dict]] = {}
            for note in notes:
                note_type = note.get("note_type", "learning_notes")
                if note_type not in notes_by_type:
                    notes_by_type[note_type] = []
                notes_by_type[note_type].append(note)

            # Process each type in batch
            total_embedded = 0
            for note_type, type_notes in notes_by_type.items():
                try:
                    embeddings = embedding_service.store_note_embeddings_batch(
                        user_id=user_id,
                        notes=type_notes,
                        note_type=note_type
                    )
                    total_embedded += len(embeddings)
                except Exception as e:
                    logger.error(
                        f"Failed to store embeddings for {note_type} | "
                        f"user_id={user_id} | error={e}"
                    )

            if total_embedded > 0:
                logger.info(
                    f"Generated {total_embedded} note embeddings | user_id={user_id}"
                )

        except Exception as e:
            # Don't fail the main operation if embedding generation fails
            logger.error(f"Embedding generation failed | user_id={user_id} | error={e}")

    def create_event(
        self,
        *,
        profile_id: str,
        event_type: str,
        event_data: dict,
        trigger_context: Optional[dict],
        processing_status: str = "pending",
    ) -> MemoryEvent:
        event = self.event_repo.create(
            self.db,
            user_memory_profile_id=profile_id,
            event_type=event_type,
            event_data=event_data,
            trigger_context=trigger_context,
            processing_status=processing_status,
        )
        # Ensure we have an ID available immediately
        self.db.flush()
        return event

    def update_event_status(
        self,
        event: MemoryEvent,
        *,
        status: str,
        reasoning: Optional[str] = None,
        notes_added: Optional[list] = None,
    ) -> MemoryEvent:
        return self.event_repo.update_status(
            self.db,
            event,
            status=status,
            reasoning=reasoning,
            notes_added=notes_added,
        )

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()
