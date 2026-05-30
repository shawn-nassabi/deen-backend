---
phase: 260530-ddo-skip-quiz-pages
plan: 01
subsystem: hikmah-generation
tags: [hikmah, scripts, refactor, data-ingestion]
dependency_graph:
  requires: []
  provides:
    - "Hikmah upserts no longer create blank quiz pages; MCQs attach to the last text page."
  affects:
    - scripts/hikmah_generation/upsert_hikmah_tree.py
tech_stack:
  added: []
  patterns:
    - "in-place mutation of payload['hikmah_tree']['meta']['total_pages'] before _insert_tree call"
    - "last_text_page tracking variable across order_position-sorted lesson content loop"
key_files:
  created: []
  modified:
    - scripts/hikmah_generation/upsert_hikmah_tree.py
decisions:
  - "Mutated meta in place rather than changing _insert_tree signature — keeps the diff minimal and preserves the existing tree_data.get('meta') contract."
  - "Used PEP 604 union (LessonContent | None) to match existing style in the same file (HikmahTree | None on line 169)."
  - "Quiz-first lessons raise ValidationError rather than silently swallowing MCQs."
metrics:
  duration: "~5 minutes"
  completed: 2026-05-30
---

# Quick Task 260530-ddo: Skip Quiz Pages in Hikmah Upsert Summary

Modified `scripts/hikmah_generation/upsert_hikmah_tree.py` so quiz entries no longer create blank `lesson_content` rows — their MCQs are attached to the last-inserted text page of the same lesson, and `meta.total_pages` reflects the real text-page count.

## Changes

1. **Module docstring (lines 4–9):** Added a sentence describing the new attachment behavior alongside the existing five-table description.
2. **`upsert_hikmah_tree` per-lesson loop (now lines 393–421):** Replaced the unconditional `_insert_content` + post-hoc `if content_type == "quiz"` block with a branched loop:
   - Text branch: insert page, increment `counts["pages"]`, store as `last_text_page`.
   - Quiz branch: skip `_insert_content`, do NOT increment `counts["pages"]`, raise `ValidationError` if `last_text_page is None`, attach each MCQ to `last_text_page.id`.
3. **`meta.total_pages` overwrite (lines 375–388):** Inserted a block immediately before `tree = _insert_tree(...)` that recomputes `total_pages` from the number of text entries across all lessons and writes it into `payload["hikmah_tree"]["meta"]` in place. Only fires when `meta` is a dict AND the `total_pages` key was already present — never invents the key.
4. **`counts["pages"]` correctness:** Increment is now reachable only from the text branch (Edit 4 satisfied via Edit 2's structure).

Unchanged: `_validate_payload`, `_insert_tree`, `_insert_content`, `_insert_mcq`, schemas, models, and `generate_hikmah_tree.py` (explicitly excluded by user).

## Verification

### Automated (syntax + grep markers)

```
syntax ok
399:        last_text_page: LessonContent | None = None
406:                last_text_page = page
410:            if last_text_page is None:
419:                _, choices = _insert_mcq(db, last_text_page.id, mcq, order_position=m_idx)
---
376:    # Recompute meta.total_pages so it reflects only text-page rows we will insert
378:    # the input did not declare total_pages. _insert_tree reads tree_data.get("meta")
381:    if isinstance(tree_meta, dict) and "total_pages" in tree_meta:
388:        tree_meta["total_pages"] = total_text_pages
```

### Dry-run against `fundamentals-of-islam_db.json`

```
Loading /Users/shawn.n/Desktop/Deen/deen-backend/scripts/hikmah_generation/fundamentals_of_islam/fundamentals-of-islam_db.json...
Validating payload...
[replace] Deleted existing tree 'Fundamentals of Islam': 5 lessons, 19 content pages (quiz questions/choices cascaded).

[dry-run] Rolled back. Summary of what WOULD have been inserted:
  hikmah_tree.id    = 5
  hikmah_tree.title = 'Fundamentals of Islam'
  lessons inserted  = 5
  pages inserted    = 14
  questions inserted= 20
  choices inserted  = 80
```

All plan-stated expectations met:

| Field                | Expected            | Observed | Pass |
| -------------------- | ------------------- | -------- | ---- |
| `lessons inserted`   | 5                   | 5        | yes  |
| `pages inserted`     | 14 (text-only)      | 14       | yes  |
| `questions inserted` | non-zero            | 20       | yes  |
| `choices inserted`   | non-zero            | 80       | yes  |

The pre-existing tree had **19 content pages** (14 text + 5 quiz) — the new behavior writes only the 14 text rows, confirming the quiz branch no longer inserts a `lesson_content` row. `meta.total_pages` resolves to 14 because the input declared the key and the new overwrite block recomputes it from the actual text-entry count.

### Files modified

```
M scripts/hikmah_generation/upsert_hikmah_tree.py
```

Only the target file. `generate_hikmah_tree.py` untouched (per constraint).

## Deviations from Plan

None — plan executed exactly as written.

## Commits

- `64e3635` — fix(hikmah): skip quiz page rows and attach MCQs to last text page

## Self-Check: PASSED

- FOUND: scripts/hikmah_generation/upsert_hikmah_tree.py (modified)
- FOUND: commit 64e3635 in git log
