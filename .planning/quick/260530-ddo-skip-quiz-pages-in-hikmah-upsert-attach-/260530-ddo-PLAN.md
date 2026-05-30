---
phase: 260530-ddo-skip-quiz-pages
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/hikmah_generation/upsert_hikmah_tree.py
autonomous: true
requirements:
  - QUICK-01
must_haves:
  truths:
    - "Quiz entries in lesson content do not create their own LessonContent row."
    - "MCQs from a quiz entry are attached (via lesson_content_id FK) to the last-inserted text page of the same lesson."
    - "If a lesson's content array begins with a quiz (no preceding text page), upsert raises ValidationError with a clear message."
    - "After upsert, hikmah_tree.meta.total_pages (when present in input) reflects the actual number of inserted text pages across all lessons."
    - "main()'s summary shows counts['pages'] equal to the count of inserted text pages only (quiz entries excluded)."
  artifacts:
    - path: "scripts/hikmah_generation/upsert_hikmah_tree.py"
      provides: "Modified upsert orchestration that skips quiz-page row insertion and attaches MCQs to last text page"
      contains: "last_text_page_id"
  key_links:
    - from: "upsert_hikmah_tree (per-lesson loop ~lines 377-390)"
      to: "_insert_mcq"
      via: "lesson_content_id derived from last-inserted text page, not from a quiz page row"
      pattern: "_insert_mcq\\(db, last_text_page.*\\.id"
    - from: "_insert_tree"
      to: "hikmah_tree.meta['total_pages']"
      via: "post-count overwrite after orchestration walks all lessons OR computed-once in orchestrator before _insert_tree call"
      pattern: "total_pages.*=.*"
---

<objective>
Modify `scripts/hikmah_generation/upsert_hikmah_tree.py` so that `content_type: "quiz"` entries in the input JSON do NOT create a blank `LessonContent` row. Instead, their MCQs attach to the last-inserted text page for the same lesson. Also ensure `hikmah_tree.meta.total_pages` (when present) reflects the actual count of inserted text pages, and the `main()` summary's page count is correct.

Purpose: Today the script creates blank quiz "pages" (content_body=NULL, content_type="quiz") in `lesson_content`, then attaches quiz questions to those blank pages. The frontend hikmah experience treats every `LessonContent` row as a page in its own right, so these blank quiz pages render as empty content. The fix moves MCQ attachment onto the last actual text page of the lesson, eliminating the blank-page artifact while keeping the existing input JSON format unchanged.

Output: Updated `upsert_hikmah_tree.py` (no other files touched).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@CLAUDE.md
@scripts/hikmah_generation/upsert_hikmah_tree.py
@scripts/hikmah_generation/fundamentals_of_islam/fundamentals-of-islam_db.json

<interfaces>
<!-- Key functions/types in the file being edited. Already extracted; do not re-explore. -->

From scripts/hikmah_generation/upsert_hikmah_tree.py:

- `class ValidationError(Exception)` — raised when input JSON does not match expected schema. Re-use this for the new "lesson starts with quiz" failure.

- `_validate_payload(payload)` — validates input JSON. Currently REQUIRES `content_body` on text entries and `content_json.mcqs` on quiz entries. Already validates `content_type in {"text", "quiz"}`. **Do not change this function** — the JSON format is unchanged; only insertion behavior changes.

- `_insert_tree(db, tree_data) -> HikmahTree` (lines 218–228) — currently writes `meta=tree_data.get("meta")` directly. Either mutate `tree_data["meta"]` BEFORE calling this (in the orchestrator) so the existing _insert_tree picks up the corrected count, OR change _insert_tree to accept an explicit override. Prefer the former: compute `total_text_pages` in `upsert_hikmah_tree(...)` before the `_insert_tree(...)` call and mutate `payload["hikmah_tree"]["meta"]["total_pages"]` in place (only if `meta` is a dict AND already has the `total_pages` key — do not invent the key).

- `_insert_content(db, content_data, lesson_id) -> LessonContent` — inserts one LessonContent row. After this change, only called for text entries.

- `_insert_mcq(db, lesson_content_id, mcq, order_position)` — attaches an MCQ + choices to a given `lesson_content_id`. Now called with the last text page's `id`, not a quiz page's `id`.

- `upsert_hikmah_tree(db, payload, replace)` (lines 322–396) — orchestrator. The per-lesson loop (lines 377–390) is the primary edit site.

Schema confirmation from input JSON: a quiz entry has `content_type: "quiz"`, `content_body: null`, and `content_json: { "mcqs": [...] }`. It always appears at `order_position: 99` (i.e., last) for each lesson in the current dataset, but the code MUST NOT rely on that — iterate in `order_position` order and track the last text page seen, exactly as the spec requires.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Refactor upsert_hikmah_tree.py to skip quiz page rows and attach MCQs to last text page</name>
  <files>scripts/hikmah_generation/upsert_hikmah_tree.py</files>
  <action>
Make four coordinated edits in `scripts/hikmah_generation/upsert_hikmah_tree.py`. Do NOT touch `generate_hikmah_tree.py` (excluded by user).

**Edit 1 — Module docstring (lines 1–21):** Add one sentence to the existing docstring (not a new docstring block) noting the new behavior. Insert it after the existing "five tables" sentence around line 6. Suggested wording:

> "Quiz entries (`content_type == "quiz"`) in the input do NOT create their own `lesson_content` row — their MCQs are attached to the last-inserted text page of the same lesson."

Keep the existing Usage / Modes sections intact.

**Edit 2 — Per-lesson loop in `upsert_hikmah_tree` (current lines 377–390):** Replace the body of the inner `for content_data in sorted(lesson_data["content"], ...)` loop so that:

1. Iterate entries in `order_position` order (the existing `sorted(...)` call is correct — keep it).
2. Maintain a `last_text_page` local variable, reset to `None` at the start of each lesson.
3. For `content_type == "text"`:
   - Call `_insert_content(db, content_data, lesson.id)` as today.
   - Increment `counts["pages"] += 1`.
   - Assign the returned `page` to `last_text_page`.
4. For `content_type == "quiz"`:
   - Do NOT call `_insert_content`.
   - Do NOT increment `counts["pages"]`.
   - If `last_text_page is None`, raise `ValidationError` with a clear message that includes the lesson slug and order_position of the offending quiz entry. Example:
     `raise ValidationError(f"Lesson {lesson_data['slug']!r} content begins with a quiz entry (order_position={content_data['order_position']}) before any text page — cannot attach MCQs.")`
   - Iterate `content_data["content_json"]["mcqs"]` with `enumerate(..., start=1)` and call `_insert_mcq(db, last_text_page.id, mcq, order_position=m_idx)`. Increment `counts["questions"]` and `counts["choices"]` exactly as today.

The replacement loop should look approximately like:

```python
for lesson_data in sorted(payload["lessons"], key=lambda l: l.get("order_position") or 0):
    lesson = _insert_lesson(db, lesson_data, tree.id)
    counts["lessons"] += 1

    last_text_page: LessonContent | None = None
    for content_data in sorted(lesson_data["content"], key=lambda c: c["order_position"]):
        content_type = content_data["content_type"]

        if content_type == "text":
            page = _insert_content(db, content_data, lesson.id)
            counts["pages"] += 1
            last_text_page = page
            continue

        # content_type == "quiz"
        if last_text_page is None:
            raise ValidationError(
                f"Lesson {lesson_data['slug']!r} content begins with a quiz entry "
                f"(order_position={content_data['order_position']}) before any text page — "
                f"cannot attach MCQs."
            )

        mcqs = content_data["content_json"]["mcqs"]
        for m_idx, mcq in enumerate(mcqs, start=1):
            _, choices = _insert_mcq(db, last_text_page.id, mcq, order_position=m_idx)
            counts["questions"] += 1
            counts["choices"] += len(choices)
```

Use the typing form `LessonContent | None` (PEP 604, fine on Python 3.11 — matches the existing style in the file, e.g. `HikmahTree | None` on line 169).

**Edit 3 — meta.total_pages overwrite:** Compute the actual number of text pages across all lessons BEFORE calling `_insert_tree(db, payload["hikmah_tree"])` on line 373, and overwrite `payload["hikmah_tree"]["meta"]["total_pages"]` only if `meta` is a dict and `"total_pages"` is already a key. Do NOT add the key when absent. Insert this block immediately before line 373 (after the `--replace` deletion block, before `tree = _insert_tree(...)`):

```python
# Recompute meta.total_pages so it reflects only text-page rows we will insert
# (quiz entries no longer create their own page row). Leave meta untouched if
# the input did not declare total_pages.
tree_meta = payload["hikmah_tree"].get("meta")
if isinstance(tree_meta, dict) and "total_pages" in tree_meta:
    total_text_pages = sum(
        1
        for lesson in payload["lessons"]
        for entry in lesson["content"]
        if entry["content_type"] == "text"
    )
    tree_meta["total_pages"] = total_text_pages
```

Leave `_insert_tree` itself unchanged — it already reads `tree_data.get("meta")`, so mutating `payload["hikmah_tree"]["meta"]` in place is sufficient. (Note in your inline comment that this is why _insert_tree is not modified.)

**Edit 4 — counts['pages'] correctness:** Edit 2 already enforces this (increment only inside the `if content_type == "text":` branch). Double-check before committing that `counts["pages"] += 1` is no longer reachable from the quiz branch.

**Constraints reminder:**
- `_validate_payload` stays as-is (text entries still require `content_body`, quiz entries still require `content_json.mcqs`).
- No changes to schema, models, migrations, or any other file.
- Preserve existing imports and the `ValidationError` class.
- Follow project conventions: 4-space indent, snake_case, type hints on touched code.
  </action>
  <verify>
    <automated>cd /Users/shawn.n/Desktop/Deen/deen-backend &amp;&amp; python -c "import ast; ast.parse(open('scripts/hikmah_generation/upsert_hikmah_tree.py').read()); print('syntax ok')" &amp;&amp; python -m py_compile scripts/hikmah_generation/upsert_hikmah_tree.py &amp;&amp; grep -n "last_text_page" scripts/hikmah_generation/upsert_hikmah_tree.py | grep -v '^#' &amp;&amp; grep -n "total_pages" scripts/hikmah_generation/upsert_hikmah_tree.py | grep -v '^#'</automated>
  </verify>
  <done>
- File parses and byte-compiles cleanly.
- `grep` confirms `last_text_page` is referenced multiple times in the orchestration loop and `total_pages` appears in the meta-overwrite block.
- Manual reading of the per-lesson loop confirms: quiz branch does NOT call `_insert_content`, does NOT increment `counts["pages"]`, raises `ValidationError` when `last_text_page is None`, and passes `last_text_page.id` to `_insert_mcq`.
- Manual reading confirms the meta-overwrite block sits BEFORE the `_insert_tree(...)` call on line ~373 and only mutates when `meta` is a dict AND `total_pages` key exists.
- Module docstring contains one new sentence about quiz entries not creating their own page row.
- `generate_hikmah_tree.py` is untouched (`git status` shows only `upsert_hikmah_tree.py` modified).
  </done>
</task>

</tasks>

<verification>
After Task 1, perform a dry-run against the provided input JSON to confirm end-to-end behavior:

```bash
cd /Users/shawn.n/Desktop/Deen/deen-backend
source venv/bin/activate 2>/dev/null || true
python scripts/hikmah_generation/upsert_hikmah_tree.py \
  scripts/hikmah_generation/fundamentals_of_islam/fundamentals-of-islam_db.json \
  --replace --dry-run
```

Expected dry-run summary for `fundamentals-of-islam_db.json` (5 lessons, each with a trailing quiz, current input declares `meta.total_pages = 14`):

- `lessons inserted  = 5`
- `pages inserted    = 14` (text pages only — matches `meta.total_pages` after the overwrite)
- `questions inserted` and `choices inserted` should be non-zero and equal to the previous counts before the change (quiz attachment count is unchanged; only the page it attaches to differs).

If `pages inserted` shows a value greater than the number of text entries (i.e., quiz entries leaked into the count), Edit 4 was not applied correctly.

Negative-path sanity check (optional, manual): briefly add a synthetic quiz-first lesson to a copy of the JSON and re-run; the script should exit with a `ValidationError` referencing the lesson slug.
</verification>

<success_criteria>
- `scripts/hikmah_generation/upsert_hikmah_tree.py` parses, compiles, and the dry-run command above completes with `pages inserted = 14` and a non-zero `questions inserted` count.
- `git diff --name-only` shows only `scripts/hikmah_generation/upsert_hikmah_tree.py` modified.
- The four edits (docstring sentence, per-lesson loop refactor, meta overwrite, page-count correctness) are all present in the diff.
</success_criteria>

<output>
After completion, write a brief summary to `.planning/quick/260530-ddo-skip-quiz-pages-in-hikmah-upsert-attach-/260530-ddo-SUMMARY.md` describing the changes made and the dry-run result.
</output>
