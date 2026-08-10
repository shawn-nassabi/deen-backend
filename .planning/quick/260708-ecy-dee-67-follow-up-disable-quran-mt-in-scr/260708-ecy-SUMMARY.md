---
phase: 260708-ecy
plan: 01
subsystem: api
tags: [batch-mt, translation, quran, cli-guard, deterministic-tests]

# Dependency graph
requires:
  - phase: 260707-pxt
    provides: scripts/translate_references.py batch MT job + tests/test_translate_references.py deterministic test suite
provides:
  - DISABLED_REF_TYPES module-level constant on scripts/translate_references.py holding quran_translation out of the batch MT job
  - _resolve_enabled_ref_types(ref_type_arg) helper used by main() to filter requested ref_types and log a warning per skipped type
  - main() early-return with a logged ERROR (before any Anthropic/Pinecone/DB client construction) when the enabled ref_type set is empty
  - 5 new deterministic tests in TestResolveEnabledRefTypes covering the guard
affects: [dee-67, reference-translation-batch-job]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Reversible feature hold-out via a module-level DISABLED_REF_TYPES set + a filtering helper called before any external client construction, rather than deleting/commenting code"

key-files:
  created: []
  modified:
    - scripts/translate_references.py
    - tests/test_translate_references.py

key-decisions:
  - "Held Quran MT out via a set-based guard (DISABLED_REF_TYPES) rather than removing quran_translation from REF_TYPE_CHOICES, keeping the reversal a one-line diff"
  - "Guard runs in main() before _get_translation_client()/Pinecone() construction, so a fully-disabled request never touches Anthropic, Pinecone, or the DB"

patterns-established:
  - "CLI batch jobs that support --ref-type=all should filter through a dedicated _resolve_enabled_*() helper rather than inlining exclusion logic in main()"

requirements-completed: [DEE-67]

# Metrics
duration: 15min
completed: 2026-07-08
---

# Phase 260708-ecy Plan 01: Disable Quran MT in translate_references.py Summary

**DISABLED_REF_TYPES guard + `_resolve_enabled_ref_types()` helper prevent `scripts/translate_references.py` from ever pivot-translating (Arabic → English → target language) the already-English-rendered Quran text, while leaving hadith/tafsir MT fully functional.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-07-08T17:22:24Z
- **Completed:** 2026-07-08T17:33:06Z
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments
- Added `DISABLED_REF_TYPES = {"quran_translation"}` (with rationale comment) adjacent to `REF_TYPE_CHOICES`
- Added `_resolve_enabled_ref_types(ref_type_arg: str) -> list[str]` that filters requested ref_types against the disabled set, logging a WARNING per skipped type, preserving `REF_TYPE_CHOICES` order
- `main()` now calls the helper and returns early with a logged ERROR before any Anthropic/Pinecone client construction when the enabled subset is empty
- Updated the module docstring's first sentence to reflect the hold-out
- Added 5 deterministic tests (`TestResolveEnabledRefTypes`) proving `--ref-type all` yields `["hadith", "tafsir_text"]`, `--ref-type quran_translation` yields `[]` and logs a WARNING, single-type passthrough is unaffected, and `DISABLED_REF_TYPES` stays pinned to `{"quran_translation"}`

## Task Commits

Each task was committed atomically:

1. **Task 1: Add DISABLED_REF_TYPES guard and _resolve_enabled_ref_types helper** - `7369d98` (feat)
2. **Task 2: Deterministic tests for the disabled-ref-type guard** - `82f8cc8` (test)

**Plan metadata:** committed separately by the orchestrator (not by this executor)

## Files Created/Modified
- `scripts/translate_references.py` - `DISABLED_REF_TYPES` constant, `_resolve_enabled_ref_types()` helper, `main()` guard + early-return, updated module docstring
- `tests/test_translate_references.py` - new `TestResolveEnabledRefTypes` class (5 tests) + updated imports

## Decisions Made
- Held Quran MT out via a set-based guard rather than editing `REF_TYPE_CHOICES` itself, so re-enabling is a one-line removal from `DISABLED_REF_TYPES` (per plan's `must_haves`)
- Placed the empty-set early-return in `main()` immediately after `_resolve_enabled_ref_types()`, strictly before `_get_translation_client()` / `Pinecone(...)` construction, so a fully-disabled request never reaches any external service

## Deviations from Plan

None - plan executed exactly as written. `REF_TYPE_CHOICES`, `run_batch`, `_extract_text_for_ref_type`, `_index_name_for_ref_type`, `upsert_translation`, `translate_text`, and the argparse `--ref-type` choices were left untouched, as required.

## Issues Encountered
- The worktree had no Python virtualenv. Installed dependencies from `requirements.txt` into the repo's shared `venv/` (substituting `torch==2.2.2` for the pinned `torch==2.6.0`, which has no wheel for this Python/platform combination, per the task's explicit constraint) so `pytest` could run. This is an environment-setup step only; no application code depends on the torch version difference for these tests (torch is a transitive import via `sentence-transformers`/`langchain-huggingface`, unrelated to the translation batch job's logic).
- No git/code deviations otherwise.

## User Setup Required

None - no external service configuration required. `DISABLED_REF_TYPES` is a plain in-repo constant; no env vars or infra changes.

## Next Phase Readiness
- `scripts/translate_references.py --ref-type all` (the default) is now safe to run against the live corpus without risk of double-translating Quran text
- Re-enabling Quran MT later requires only removing `"quran_translation"` from `DISABLED_REF_TYPES`
- No blockers for DEE-67 batch-job usage going forward

---
*Phase: 260708-ecy*
*Completed: 2026-07-08*

## Self-Check: PASSED

All claimed files and commits verified present:
- FOUND: scripts/translate_references.py
- FOUND: tests/test_translate_references.py
- FOUND: .planning/quick/260708-ecy-dee-67-follow-up-disable-quran-mt-in-scr/260708-ecy-SUMMARY.md
- FOUND: 7369d98
- FOUND: 82f8cc8
