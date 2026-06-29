---
phase: 260629-ia2
plan: "01"
subsystem: hikmah-elaboration
tags: [prompt-engineering, regression-test, dee-55, real_llm]
dependency_graph:
  requires: []
  provides: [corrected-hikmah-refusal-boundary]
  affects: [POST /hikmah/elaborate]
tech_stack:
  added: []
  patterns: [pytestmark-real_llm, agenerate_elaboration_response_stream]
key_files:
  modified:
    - core/prompt_templates.py
  created:
    - tests/test_hikmah_elaboration_refusal.py
decisions:
  - "Reworded refusal bullet to enumerate empty/whitespace/punctuation/random-char cases explicitly; added affirmative clause naming Islamic/Arabic terms as always-sufficient — no structural change to prompt"
  - "Test file uses pytestmark = pytest.mark.real_llm so it is excluded from default CI (addopts = -m 'not real_llm' in pytest.ini)"
  - "Refusal detection in test uses substring 'not sufficient for me to provide an explanation' which matches regardless of the smart-apostrophe in the prompt prefix"
metrics:
  duration: "~6 minutes"
  completed_date: "2026-06-29"
  tasks_completed: 2
  files_changed: 2
---

# Phase 260629-ia2 Plan 01: Fix DEE-55 Hikmah Over-Refusal on Short Meaningful Terms Summary

**One-liner:** Reworded hikmah elaboration refusal bullet to explicitly permit single Islamic/Arabic terms (Imam, Tawhid, 'Adl, hadith) while still refusing empty/whitespace/nonsensical input; locked by an opt-in real_llm regression test.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Reword over-restrictive refusal bullet in hikmahElaborationSystemTemplate | 42566a3 | core/prompt_templates.py |
| 2 | Add opt-in regression test for the elaboration refusal boundary | 14b6480 | tests/test_hikmah_elaboration_refusal.py |

## What Was Done

**Task 1 — Prompt fix (core/prompt_templates.py line 318):**

Replaced the ambiguous bullet:
> "If the selected text is too short, nonsensical, or lacks meaning (e.g., single conjunctions, random characters, punctuation, or whitespace)..."

With an explicit reword that:
- Enumerates the true refusal triggers: empty, whitespace-only, punctuation-only, random characters, or isolated function words with no Islamic meaning ("and", "the", "of")
- Adds an affirmative clause: "A single meaningful word or short term — including a concept, name, place, or any Islamic/Arabic term such as Imam, Tawhid, 'Adl, hadith, mawazin, or Usul al-Din — IS sufficient input and must be elaborated upon."
- Preserves the verbatim refusal sentence the frontend and tests match on

No other lines in the file were changed.

**Task 2 — Regression test (tests/test_hikmah_elaboration_refusal.py):**

Created an opt-in `real_llm`-marked test file with:
- `test_meaningful_terms_not_refused`: drives `agenerate_elaboration_response_stream` for each of ["Imam", "Tawhid", "'Adl", "hadith"] and asserts the refusal fragment is absent
- `test_junk_input_refused`: drives the same function for ["...", "   ", "###"] and asserts the refusal fragment is present
- `pytestmark = pytest.mark.real_llm` excludes from default `pytest tests -q` run
- Direct function call (no server required)

## Verification Results

1. `grep "single meaningful word or short term" core/prompt_templates.py` — returns exactly one match at line 318.
2. `grep "not sufficient for me to provide an explanation" core/prompt_templates.py` — returns exactly one match at line 318 (refusal sentence preserved; uses smart apostrophe in prompt, test matches on the unambiguous substring).
3. `python3 -m py_compile tests/test_hikmah_elaboration_refusal.py` — syntax OK.
4. AST inspection confirms: `pytestmark = pytest.mark.real_llm`, two `@pytest.mark.asyncio` async test functions, async `_run` helper.
5. `pytest.ini addopts = -m "not real_llm"` ensures both new tests are excluded from the default suite.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None. The reworded bullet is prompt text only; the existing input sanitisation path and trust boundary (user `selected_text` → prompt injection) are unchanged.

## Self-Check: PASSED

- core/prompt_templates.py modified: FOUND
- tests/test_hikmah_elaboration_refusal.py created: FOUND
- Commit 42566a3: FOUND
- Commit 14b6480: FOUND
