"""
Concurrency tests for MemoryService.get_or_create_profile.

Regression guard for the Sentry bug captured in
.planning/debug/quiz-memory-profile-dup-key.md: two requests racing to create
a UserMemoryProfile for the same fresh user_id used to crash the loser with
psycopg2.errors.UniqueViolation. The fix wraps the create branch in a
savepoint and recovers by re-fetching the winner's row.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from contextlib import contextmanager
from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy.exc import IntegrityError

from agents.models.user_memory_models import UserMemoryProfile
from services.memory_service import MemoryService


def _make_savepoint_cm():
    """Return a context manager that mimics db.begin_nested() — a no-op
    that must enter and exit cleanly. Tests that need to assert savepoint
    rollback simply rely on the IntegrityError propagating out of the
    `with` block."""

    @contextmanager
    def _cm():
        yield

    return _cm


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.begin_nested = Mock(side_effect=_make_savepoint_cm())
    return db


@pytest.fixture
def profile_repo():
    return Mock()


@pytest.fixture
def event_repo():
    return Mock()


@pytest.fixture
def service(mock_db, profile_repo, event_repo):
    return MemoryService(db=mock_db, profile_repo=profile_repo, event_repo=event_repo)


def _fake_profile(user_id: str, profile_id: str = "p-1") -> UserMemoryProfile:
    return UserMemoryProfile(id=profile_id, user_id=user_id)


def test_returns_existing_profile_without_creating(service, profile_repo, mock_db):
    """If a profile already exists, no INSERT, no savepoint, no flush."""
    existing = _fake_profile("user-existing", profile_id="p-existing")
    profile_repo.get_by_user_id.return_value = existing

    result = service.get_or_create_profile("user-existing")

    assert result is existing
    profile_repo.create.assert_not_called()
    mock_db.begin_nested.assert_not_called()
    mock_db.flush.assert_not_called()


def test_creates_profile_when_missing_happy_path(service, profile_repo, mock_db):
    """Race winner: SELECT misses, savepoint enters, INSERT + flush succeed,
    profile is returned."""
    created = _fake_profile("user-new")
    profile_repo.get_by_user_id.return_value = None
    profile_repo.create.return_value = created

    result = service.get_or_create_profile("user-new")

    assert result is created
    mock_db.begin_nested.assert_called_once()
    profile_repo.create.assert_called_once()
    mock_db.flush.assert_called_once()
    # Only the initial lookup happened — no second SELECT after a successful
    # create (there was no IntegrityError to recover from).
    assert profile_repo.get_by_user_id.call_count == 1


def test_race_loser_recovers_winners_row(service, profile_repo, mock_db):
    """Regression test for the Sentry bug.

    Simulates the loser of a get_or_create race: the initial SELECT misses,
    the savepoint INSERT raises IntegrityError (the winner's row landed
    first), and the recovery re-SELECT now finds the winner's row. The
    method must return that row instead of bubbling the IntegrityError up
    to callers."""
    winners_row = _fake_profile("user-race", profile_id="p-winner")

    # First lookup: nothing yet. Second lookup (the recovery re-fetch):
    # winner's row is now visible.
    profile_repo.get_by_user_id.side_effect = [None, winners_row]

    # Simulate the unique-violation surfacing inside the savepoint.
    mock_db.flush.side_effect = IntegrityError(
        statement="INSERT INTO user_memory_profiles ...",
        params={},
        orig=Exception(
            'duplicate key value violates unique constraint '
            '"uq_user_memory_profiles_user_id"'
        ),
    )

    result = service.get_or_create_profile("user-race")

    assert result is winners_row
    # Both the initial and the recovery lookup ran.
    assert profile_repo.get_by_user_id.call_count == 2
    # We did try to create — the failure was during flush, not before it.
    profile_repo.create.assert_called_once()
    # And we entered the savepoint exactly once.
    mock_db.begin_nested.assert_called_once()


def test_unrelated_integrity_error_propagates(service, profile_repo, mock_db):
    """If the IntegrityError is NOT the unique-violation race (e.g. a
    foreign-key constraint, a NOT NULL violation, or something else), the
    recovery re-SELECT also returns None — there is no winner to fall back
    to. In that case the original IntegrityError must propagate so the
    caller sees the real failure instead of a silent None or a stale row."""
    profile_repo.get_by_user_id.side_effect = [None, None]
    mock_db.flush.side_effect = IntegrityError(
        statement="INSERT ...",
        params={},
        orig=Exception("null value in column \"some_other_col\""),
    )

    with pytest.raises(IntegrityError):
        service.get_or_create_profile("user-broken")

    profile_repo.create.assert_called_once()
    assert profile_repo.get_by_user_id.call_count == 2
