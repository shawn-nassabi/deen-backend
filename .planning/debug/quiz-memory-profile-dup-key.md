---
slug: quiz-memory-profile-dup-key
status: resolved
trigger: |
  Sentry: "Failed to process incorrect quiz memory event" — IntegrityError UniqueViolation
  on uq_user_memory_profiles_user_id when get_or_create_profile() in
  services/memory_service.py flushes a new UserMemoryProfile insert.
  Surfaced from _trigger_incorrect_quiz_memory_event in services/hikmah_quiz_service.py
  via memory_agent.analyze_interaction → _get_or_create_memory_profile.
created: 2026-05-10
updated: 2026-05-10
---

# Debug Session: quiz-memory-profile-dup-key

## Symptoms

- **Expected behavior:** When a user submits an incorrect quiz answer,
  `_trigger_incorrect_quiz_memory_event` should call
  `memory_agent.analyze_interaction(user_id, ...)`, which fetches OR creates the user's
  `UserMemoryProfile` row exactly once, then proceeds to record a `MemoryEvent`.
- **Actual behavior:** `MemoryService.get_or_create_profile(user_id)` runs a SELECT,
  finds no profile, builds a new `UserMemoryProfile`, and the subsequent
  `self.db.flush()` raises `psycopg2.errors.UniqueViolation`:
  `duplicate key value violates unique constraint "uq_user_memory_profiles_user_id"`
  for `user_id=b950742e-14b4-4701-a467-b064908dc040`. The whole memory-event side-effect
  is lost; the quiz submission itself succeeded.
- **Error message:** see Sentry exception captured 2026-05-07T01:45:16.622Z (full
  traceback below in Evidence). SQLState 23505. Background:
  https://sqlalche.me/e/20/gkpj
- **Timeline:** Observed in Sentry on 2026-05-07. Likely pre-existing — surfaces
  whenever a profile-less user triggers two memory-event-emitting flows in quick
  succession (e.g. chat turn + quiz attempt) or concurrent quiz attempts.
- **Reproduction (suspected):** Issue an incorrect quiz submission for a user_id that
  has no existing `user_memory_profiles` row, ideally concurrently with another
  request that also calls `get_or_create_profile` for the same user_id (or where one
  insert has committed since the SELECT). The user_id from Sentry
  (`b950742e-14b4-4701-a467-b064908dc040`) likely now has a row, so reproduction
  needs a fresh user_id.

## Initial Analysis Hints (for debugger)

The Sentry breadcrumbs already tell most of the story:

```
01:45:08.068Z  SELECT user_memory_profiles WHERE user_id = :user_id LIMIT 1   (returned 0 rows)
01:45:08.076Z  INSERT INTO user_memory_profiles (...) VALUES (...)            (queued in flush)
01:45:16.622Z  UniqueViolation: uq_user_memory_profiles_user_id duplicate
```

That is the textbook check-then-insert race. Two readers see "no profile",
both try to insert, the second loses on the unique constraint. Confirm the
hypothesis by reading the actual `MemoryService.get_or_create_profile`
implementation (`services/memory_service.py:47` is the failing flush line) —
expect a pattern like:

```python
profile = self.db.query(UserMemoryProfile).filter_by(user_id=user_id).first()
if profile:
    return profile
profile = UserMemoryProfile(user_id=user_id, ...)
self.db.add(profile)
self.db.flush()  # <-- raises here on the loser
return profile
```

Also worth checking:

- Does `_trigger_incorrect_quiz_memory_event` use a fresh DB session
  (`asyncio.run(...)` at hikmah_quiz_service.py:300 implies a brand-new event
  loop on a thread, so probably yes — increases concurrency risk because two
  in-flight requests for the same user_id both hold their own session).
- Is there a similar race surfaced from any other memory-event call site? (chat
  flow, primer flow, etc.) — `_get_or_create_memory_profile` is on the
  `UniversalMemoryAgent`, so probably shared across triggers.
- Confirm the unique constraint name: `uq_user_memory_profiles_user_id` should
  exist in the alembic migration that introduced `user_memory_profiles`.

## Hypotheses

### Active
- **H1 — CONFIRMED:** `MemoryService.get_or_create_profile` does a non-atomic
  SELECT-then-INSERT. Concurrent requests for a user without an existing profile
  race; the second one's flush violates `uq_user_memory_profiles_user_id`.
  - **Fix shape:** make the create path atomic — either (a) use Postgres
    `INSERT ... ON CONFLICT (user_id) DO NOTHING RETURNING *` followed by a
    re-SELECT, or (b) wrap the create in a savepoint that catches
    `IntegrityError`, rolls back the inner transaction, and re-fetches the now-
    existing row. Either path makes get-or-create idempotent under concurrency.

### Eliminated
(none yet)

## Current Focus

- **hypothesis:** CONFIRMED — check-then-insert race in
  `MemoryService.get_or_create_profile`. The code at services/memory_service.py:31-48
  matches the predicted pattern exactly: `profile_repo.get_by_user_id` → if None →
  `profile_repo.create` (which does `db.add(profile)` and returns) → `self.db.flush()`.
  No `ON CONFLICT`, no `IntegrityError` handling, no row-level lock.
- **next_action:** Apply fix in `MemoryService.get_or_create_profile` using
  the savepoint approach (option b) — it stays in ORM idioms and does not require
  raw SQL or a `postgresql.insert(...)` dialect import. Awaiting user
  confirmation on (1) fix approach (savepoint vs ON CONFLICT) and (2) commit
  prefix (Linear ID vs date-stub).
- **test:** Manual concurrency repro (two parallel requests for a fresh user_id)
  before & after, plus a unit test that monkeypatches the repo to simulate the
  race window. Recommend adding `tests/test_memory_service_concurrency.py`.
- **expecting:** After fix, two concurrent calls to `get_or_create_profile` for
  the same fresh `user_id` both return the same `UserMemoryProfile` row; only one
  INSERT actually executes; no IntegrityError surfaces.

## Evidence

- timestamp: 2026-05-07T01:45:16.622Z
  source: sentry
  finding: |
    UniqueViolation on uq_user_memory_profiles_user_id, user_id =
    b950742e-14b4-4701-a467-b064908dc040. Failing INSERT parameters
    show a freshly-built profile with empty notes arrays, total_interactions=0,
    memory_version=1 — i.e. the "create" branch of get-or-create.
  full_traceback: |
    File "services/hikmah_quiz_service.py", line 300, in process_submission
        asyncio.run(...)
    File "services/hikmah_quiz_service.py", line 371, in _trigger_incorrect_quiz_memory_event
        await memory_agent.analyze_interaction(...)
    File "agents/core/universal_memory_agent.py", line 136, in analyze_interaction
        memory_profile = await self._get_or_create_memory_profile(user_id)
    File "agents/core/universal_memory_agent.py", line 518, in _get_or_create_memory_profile
        return self.memory_service.get_or_create_profile(user_id)
    File "services/memory_service.py", line 47, in get_or_create_profile
        self.db.flush()
    sqlalchemy.exc.IntegrityError: (psycopg2.errors.UniqueViolation)
        duplicate key value violates unique constraint
        "uq_user_memory_profiles_user_id"
        DETAIL: Key (user_id)=(b950742e-14b4-4701-a467-b064908dc040) already exists.

- timestamp: 2026-05-10T00:00:00Z
  source: code_read
  file: services/memory_service.py:31-48
  finding: |
    `MemoryService.get_or_create_profile` is exactly the predicted vulnerable
    shape:
    ```
    def get_or_create_profile(self, user_id: str) -> UserMemoryProfile:
        profile = self.profile_repo.get_by_user_id(self.db, user_id)
        if profile:
            return profile
        profile = self.profile_repo.create(
            self.db, user_id=user_id, defaults={...empty note lists...},
        )
        # No commit here; caller controls commit boundary
        self.db.flush()
        return profile
    ```
    No SELECT FOR UPDATE, no ON CONFLICT, no IntegrityError catch, no savepoint.
    The race window is the entire interval between the SELECT inside
    `profile_repo.get_by_user_id` and the INSERT executed by `db.flush()` — easily
    seconds when LLM calls or other I/O happen between calls (Sentry shows ~8s
    between SELECT at 08.068Z and the flushed INSERT failing at 16.622Z, because
    the assess/analysis path runs intermediate work).

- timestamp: 2026-05-10T00:00:00Z
  source: code_read
  file: db/repositories/memory_profile_repository.py:10-16
  finding: |
    `MemoryProfileRepository.get_by_user_id` is a plain
    `db.query(UserMemoryProfile).filter(...).first()` — no locking hint.
    `MemoryProfileRepository.create` is `db.add(profile); return profile` — does
    not flush. So the flush in the service is the failure point, exactly as the
    Sentry frame shows.

- timestamp: 2026-05-10T00:00:00Z
  source: code_read
  file: alembic/versions/20260407_create_memory_agent_tables.py:37
  finding: |
    Constraint name confirmed:
    `sa.UniqueConstraint('user_id', name='uq_user_memory_profiles_user_id')`.
    Plus an index `idx_user_memory_profiles_user_id` on `user_id`. Constraint
    is enforceable from `INSERT ... ON CONFLICT (user_id)` directly (matches a
    column-level unique constraint).

- timestamp: 2026-05-10T00:00:00Z
  source: code_read
  file: agents/core/universal_memory_agent.py:136,516-518,267,288
  finding: |
    `_get_or_create_memory_profile` is a one-line wrapper around
    `self.memory_service.get_or_create_profile`. The transaction commit boundary
    is `self.memory_service.commit()` at line 267 (success path) or 303 (failure
    path), well after the get-or-create call. So the flush failure happens
    inside a still-open transaction — but SQLAlchemy invalidates the session on
    IntegrityError, which is why the surrounding try/except at line 286 does
    `self.memory_service.rollback()` before attempting recovery work. That
    confirms the fix must be inside `get_or_create_profile` itself; bumping the
    catch up to `analyze_interaction` would only let us mask the symptom, not
    avoid the lost insert.

- timestamp: 2026-05-10T00:00:00Z
  source: code_read
  file: services/hikmah_quiz_service.py:291-310,334
  finding: |
    `process_submission` commits the quiz attempt (line 291) and then calls
    `asyncio.run(self._trigger_incorrect_quiz_memory_event(...))` at line 300.
    `_trigger_incorrect_quiz_memory_event` constructs a `UniversalMemoryAgent(self.db)`
    on line 334, reusing the request-scoped session. So **within a single
    request** there is only one session — the race is **across requests** (each
    request has its own session, each session does its own SELECT then INSERT).
    `asyncio.run` does not by itself create a new DB session, but it does mean
    the memory analysis runs serially on the same session that originally served
    the HTTP route.

- timestamp: 2026-05-10T00:00:00Z
  source: code_read
  file: modules/generation/stream_generator.py:209-219
  finding: |
    A second call site of `UniversalMemoryAgent` exists in the chat streaming
    path (`update_hikmah_memory_async`). It opens a **fresh** session via
    `SessionLocal()` (line 216) for each background invocation, then constructs
    `UniversalMemoryAgent(db)`. So the realistic race is: a user is mid-chat
    (background hikmah memory update is queued on session A) and simultaneously
    submits an incorrect quiz (session B). Both call `get_or_create_profile`
    for the same user_id. Whichever flushes second loses on
    `uq_user_memory_profiles_user_id`. Single-process loadtests would also
    surface this if two quiz submissions arrive within the LLM-call window.

## Root Cause

`MemoryService.get_or_create_profile` (services/memory_service.py:31-48) implements
the classic non-atomic check-then-insert pattern: `SELECT` followed by `INSERT`
with the unique constraint left to enforce idempotency. When two concurrent
sessions both observe "no profile" for the same `user_id`, both queue an INSERT
on flush; the loser's flush raises `IntegrityError` on
`uq_user_memory_profiles_user_id`. The whole `analyze_interaction` transaction
is then rolled back and the memory event side-effect is lost. The race window
spans whatever work happens between the initial `_get_or_create_memory_profile`
call and the eventual `commit()` — which includes LLM analysis, so it is easily
multiple seconds wide.

specialist_hint: python

## Proposed Fix

Make `get_or_create_profile` idempotent under concurrency by wrapping the
create branch in a `SAVEPOINT` (via `db.begin_nested()`), catching
`IntegrityError`, and re-fetching. The savepoint contains the failure to the
inner transaction so the outer session stays usable for the rest of
`analyze_interaction`.

```python
# services/memory_service.py
from sqlalchemy.exc import IntegrityError

def get_or_create_profile(self, user_id: str) -> UserMemoryProfile:
    profile = self.profile_repo.get_by_user_id(self.db, user_id)
    if profile:
        return profile

    try:
        with self.db.begin_nested():        # SAVEPOINT
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
            self.db.flush()                 # may raise IntegrityError
        return profile
    except IntegrityError:
        # Another concurrent caller inserted the profile between our
        # SELECT and INSERT. The savepoint rolled back; the outer
        # transaction is still alive. Re-SELECT and return their row.
        existing = self.profile_repo.get_by_user_id(self.db, user_id)
        if existing is None:
            # Defensive: should not happen given the unique constraint is
            # the only source of IntegrityError on this table, but guard
            # anyway so we don't return None silently.
            raise
        return existing
```

Why savepoint + IntegrityError vs `ON CONFLICT (user_id) DO NOTHING`:

1. Stays in ORM idioms — no `from sqlalchemy.dialects.postgresql import insert`,
   no JSON/UUID column-default duplication outside the `UserMemoryProfile`
   model.
2. Works regardless of which dialect we point this code at (asyncpg vs
   psycopg2 vs SQLite-in-tests).
3. Cheaper to test deterministically — we can monkeypatch
   `MemoryProfileRepository.create` to insert a competing row before the flush
   to simulate the race.

Tradeoff: in the rare loser case we do an extra SELECT round-trip. That is
acceptable — the unique constraint already serializes the create path at the
DB.

### Test plan

Add `tests/test_memory_service_concurrency.py`:

1. **happy path** — fresh user_id, single caller: returns a new profile,
   row is inserted exactly once.
2. **race winner** — fresh user_id, profile already exists in DB at SELECT
   time: returns existing row, no INSERT attempted.
3. **race loser** — monkeypatch `MemoryProfileRepository.create` (or stub the
   underlying flush) so that inside the savepoint a competing INSERT lands
   first and the local flush raises `IntegrityError`. Assert the function
   returns the competitor's row, no exception propagates, and the outer
   session is still usable (e.g. a follow-up `db.execute(select(1))` works).
4. **non-unique IntegrityError** — synthesize an unrelated IntegrityError
   inside the savepoint; assert it propagates (we don't want to swallow real
   bugs).

Also recommend a small manual / scripted concurrency probe:

```bash
# rough manual repro
python - <<'PY'
import concurrent.futures, requests
def fire():
    return requests.post(".../hikmah/quiz/submit", json={...}, headers={...}).status_code
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
    print(list(ex.map(lambda _: fire(), range(4))))
PY
```

(Use a brand-new test user_id; today's Sentry user already has a profile so
won't reproduce.)

## Resolution

- **root_cause:** Non-atomic check-then-insert in
  `MemoryService.get_or_create_profile`. Concurrent callers for the same
  unseen `user_id` both passed the SELECT-miss check, both queued an
  INSERT, the loser's flush raised `IntegrityError` on
  `uq_user_memory_profiles_user_id`, the surrounding `analyze_interaction`
  rolled back, and the memory event was silently dropped.

- **fix:** Wrapped the create branch of `get_or_create_profile` in
  `db.begin_nested()` (SAVEPOINT) and added an `IntegrityError` handler
  that re-fetches the winner's row. If the recovery SELECT still returns
  `None` the original `IntegrityError` is re-raised so unrelated
  constraint violations are not silently swallowed.

- **verification:**
  - `pytest tests/test_memory_service_concurrency.py -v` — 4/4 pass:
    1. `test_returns_existing_profile_without_creating` — short-circuit when row exists
    2. `test_creates_profile_when_missing_happy_path` — race winner / single caller
    3. `test_race_loser_recovers_winners_row` — Sentry-bug regression guard:
       savepoint flush raises `IntegrityError`, recovery SELECT returns the
       winner's row, no exception propagates
    4. `test_unrelated_integrity_error_propagates` — non-unique IntegrityError
       still surfaces to the caller
  - Broader suite: 11 unrelated pre-existing failures
    (`test_agentic_streaming_*`, `test_primer_service`,
    `test_fiqh_integration`); none import `MemoryService` or call
    `get_or_create_profile`.

- **files_changed:**
  - `services/memory_service.py` — added `IntegrityError` import and
    savepoint+recovery wrapper around the create branch.
  - `tests/test_memory_service_concurrency.py` — new file, 4 unit tests
    covering the four cases above.

- **commit:** see git log for the `260510-rmp` quick-task prefix commit.
