"""
Upsert a generated hikmah tree JSON file into the Supabase Postgres database.

Takes a `<slug>_db.json` file produced by `generate_hikmah_tree.py` and inserts
its contents across five tables: hikmah_trees, lessons, lesson_content,
lesson_page_quiz_questions, lesson_page_quiz_choices.

Quiz entries (`content_type == "quiz"`) in the input do NOT create their own
`lesson_content` row — their MCQs are attached to the last-inserted text page
of the same lesson.

Usage:
    python scripts/hikmah_generation/upsert_hikmah_tree.py <input.json>
    python scripts/hikmah_generation/upsert_hikmah_tree.py <input.json> --dry-run
    python scripts/hikmah_generation/upsert_hikmah_tree.py <input.json> --replace

Modes:
    default    Fail fast if a hikmah_trees row with the same title, or any
               lesson with a colliding slug, already exists.
    --replace  Delete the existing tree (matched by title) along with its
               lessons, content pages, quiz questions, and quiz choices
               before inserting fresh.
    --dry-run  Parse and validate the JSON, perform conflict checks, but
               roll back instead of committing. Useful for a sanity check.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Add project root to path (mirrors scripts/set_baseline_primers.py)
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy.orm import Session

from db.session import SessionLocal
from db.models.hikmah_trees import HikmahTree
from db.models.lessons import Lesson
from db.models.lesson_content import LessonContent
from db.models.lesson_page_quiz_questions import LessonPageQuizQuestion
from db.models.lesson_page_quiz_choices import LessonPageQuizChoice


VALID_CONTENT_TYPES = {"text", "quiz"}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Raised when the input JSON does not match the expected schema."""


def _validate_payload(payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValidationError("Top-level JSON must be an object")

    for key in ("hikmah_tree", "lessons"):
        if key not in payload:
            raise ValidationError(f"Missing required top-level key: {key!r}")

    tree = payload["hikmah_tree"]
    if not isinstance(tree, dict):
        raise ValidationError("'hikmah_tree' must be an object")
    if not tree.get("title"):
        raise ValidationError("hikmah_tree.title is required")

    lessons = payload["lessons"]
    if not isinstance(lessons, list) or not lessons:
        raise ValidationError("'lessons' must be a non-empty list")

    seen_slugs: set = set()
    for idx, lesson in enumerate(lessons):
        prefix = f"lessons[{idx}]"
        if not isinstance(lesson, dict):
            raise ValidationError(f"{prefix} must be an object")

        slug = lesson.get("slug")
        if not slug:
            raise ValidationError(f"{prefix}.slug is required")
        if slug in seen_slugs:
            raise ValidationError(f"Duplicate slug within input file: {slug!r}")
        seen_slugs.add(slug)

        if not lesson.get("title"):
            raise ValidationError(f"{prefix}.title is required")

        content = lesson.get("content")
        if not isinstance(content, list) or not content:
            raise ValidationError(f"{prefix}.content must be a non-empty list")

        for c_idx, item in enumerate(content):
            c_prefix = f"{prefix}.content[{c_idx}]"
            if not isinstance(item, dict):
                raise ValidationError(f"{c_prefix} must be an object")

            if item.get("order_position") is None:
                raise ValidationError(f"{c_prefix}.order_position is required")

            content_type = item.get("content_type")
            if content_type not in VALID_CONTENT_TYPES:
                raise ValidationError(
                    f"{c_prefix}.content_type must be one of {sorted(VALID_CONTENT_TYPES)}, "
                    f"got {content_type!r}"
                )

            if content_type == "text":
                if not item.get("content_body"):
                    raise ValidationError(f"{c_prefix}.content_body is required for text pages")
            else:  # quiz
                content_json = item.get("content_json")
                if not isinstance(content_json, dict):
                    raise ValidationError(f"{c_prefix}.content_json must be an object for quiz pages")
                mcqs = content_json.get("mcqs")
                if not isinstance(mcqs, list) or not mcqs:
                    raise ValidationError(f"{c_prefix}.content_json.mcqs must be a non-empty list")
                for m_idx, mcq in enumerate(mcqs):
                    _validate_mcq(mcq, f"{c_prefix}.content_json.mcqs[{m_idx}]")


def _validate_mcq(mcq: Dict[str, Any], prefix: str) -> None:
    if not isinstance(mcq, dict):
        raise ValidationError(f"{prefix} must be an object")
    if not mcq.get("question"):
        raise ValidationError(f"{prefix}.question is required")

    options = mcq.get("options")
    if not isinstance(options, list) or len(options) < 2:
        raise ValidationError(f"{prefix}.options must be a list with at least 2 entries")

    correct = mcq.get("correct_answer")
    if not correct:
        raise ValidationError(f"{prefix}.correct_answer is required")

    parsed = _parse_options(options, prefix)
    letters = [letter for letter, _ in parsed]
    if len(set(letters)) != len(letters):
        raise ValidationError(f"{prefix}.options contain duplicate letter prefixes: {letters}")
    if correct not in letters:
        raise ValidationError(
            f"{prefix}.correct_answer={correct!r} does not match any option letter in {letters}"
        )


def _parse_options(options: List[str], prefix: str) -> List[Tuple[str, str]]:
    """Split `"A) text"`-style options into (letter, text) pairs."""
    parsed: List[Tuple[str, str]] = []
    for idx, raw in enumerate(options):
        if not isinstance(raw, str) or not raw:
            raise ValidationError(f"{prefix}.options[{idx}] must be a non-empty string")
        head, sep, tail = raw.partition(") ")
        if sep and head.isalpha() and len(head) == 1:
            letter = head.upper()
            text = tail.strip()
        else:
            # Fallback: derive letter from position, keep raw as text.
            letter = chr(ord("A") + idx)
            text = raw.strip()
        if not text:
            raise ValidationError(f"{prefix}.options[{idx}] has empty text after stripping prefix")
        parsed.append((letter, text))
    return parsed


# ---------------------------------------------------------------------------
# Conflict detection and deletion
# ---------------------------------------------------------------------------

def _find_tree_by_title(db: Session, title: str) -> HikmahTree | None:
    return db.query(HikmahTree).filter(HikmahTree.title == title).first()


def _find_colliding_slugs(db: Session, slugs: List[str]) -> List[str]:
    if not slugs:
        return []
    rows = db.query(Lesson.slug).filter(Lesson.slug.in_(slugs)).all()
    return [row[0] for row in rows]


def _delete_existing_tree(db: Session, title: str) -> Dict[str, int]:
    """Delete an existing hikmah tree and all descendants (manual cascade).

    `lessons.hikmah_tree_id` and `lesson_content.lesson_id` are plain columns —
    not FK constraints — so we must delete by hand. The quiz tables DO have
    CASCADE FKs, so deleting lesson_content rows takes the questions/choices
    with them.
    """
    tree = _find_tree_by_title(db, title)
    if tree is None:
        return {"trees": 0, "lessons": 0, "content": 0}

    lesson_ids = [row[0] for row in db.query(Lesson.id).filter(Lesson.hikmah_tree_id == tree.id).all()]

    content_deleted = 0
    if lesson_ids:
        content_deleted = (
            db.query(LessonContent)
            .filter(LessonContent.lesson_id.in_(lesson_ids))
            .delete(synchronize_session=False)
        )

    lessons_deleted = (
        db.query(Lesson)
        .filter(Lesson.hikmah_tree_id == tree.id)
        .delete(synchronize_session=False)
    )

    db.delete(tree)
    db.flush()

    return {"trees": 1, "lessons": lessons_deleted, "content": content_deleted}


# ---------------------------------------------------------------------------
# Insertion
# ---------------------------------------------------------------------------

def _insert_tree(db: Session, tree_data: Dict[str, Any]) -> HikmahTree:
    tree = HikmahTree(
        title=tree_data.get("title"),
        summary=tree_data.get("summary"),
        tags=tree_data.get("tags") or [],
        skill_level=tree_data.get("skill_level"),
        meta=tree_data.get("meta"),
    )
    db.add(tree)
    db.flush()
    return tree


def _insert_lesson(db: Session, lesson_data: Dict[str, Any], hikmah_tree_id: int) -> Lesson:
    lesson = Lesson(
        slug=lesson_data["slug"],
        title=lesson_data["title"],
        summary=lesson_data.get("summary"),
        tags=lesson_data.get("tags") or [],
        status=lesson_data.get("status"),
        language_code=lesson_data.get("language_code"),
        estimated_minutes=lesson_data.get("estimated_minutes"),
        order_position=lesson_data.get("order_position"),
        hikmah_tree_id=hikmah_tree_id,
        baseline_primer_bullets=lesson_data.get("baseline_primer_bullets"),
        baseline_primer_glossary=lesson_data.get("baseline_primer_glossary"),
    )
    db.add(lesson)
    db.flush()
    return lesson


def _insert_content(db: Session, content_data: Dict[str, Any], lesson_id: int) -> LessonContent:
    content_type = content_data["content_type"]
    # For quiz pages we leave content_json NULL and rely on the normalized
    # quiz tables, which is what services/hikmah_quiz_service.py reads from.
    content_json = None if content_type == "quiz" else content_data.get("content_json")
    page = LessonContent(
        lesson_id=lesson_id,
        order_position=content_data["order_position"],
        title=content_data.get("title"),
        content_type=content_type,
        content_body=content_data.get("content_body"),
        content_json=content_json,
        media_urls=content_data.get("media_urls"),
        est_minutes=content_data.get("est_minutes"),
    )
    db.add(page)
    db.flush()
    return page


def _insert_mcq(
    db: Session,
    lesson_content_id: int,
    mcq: Dict[str, Any],
    order_position: int,
) -> Tuple[LessonPageQuizQuestion, List[LessonPageQuizChoice]]:
    parsed_options = _parse_options(mcq["options"], f"mcq(prompt={mcq['question'][:40]!r})")
    correct_letter = mcq["correct_answer"]

    difficulty = mcq.get("difficulty")
    tags = [difficulty] if difficulty else None

    question = LessonPageQuizQuestion(
        lesson_content_id=lesson_content_id,
        prompt=mcq["question"],
        explanation=None,
        tags=tags,
        order_position=order_position,
        is_active=True,
    )
    db.add(question)
    db.flush()

    choices: List[LessonPageQuizChoice] = []
    correct_count = 0
    for idx, (letter, text) in enumerate(parsed_options, start=1):
        is_correct = letter == correct_letter
        if is_correct:
            correct_count += 1
        choice = LessonPageQuizChoice(
            question_id=question.id,
            choice_key=letter,
            choice_text=text,
            order_position=idx,
            is_correct=is_correct,
        )
        db.add(choice)
        choices.append(choice)

    if correct_count != 1:
        raise ValidationError(
            f"MCQ {mcq['question'][:60]!r} has {correct_count} correct choices (expected exactly 1)"
        )

    db.flush()
    return question, choices


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def upsert_hikmah_tree(
    db: Session,
    payload: Dict[str, Any],
    replace: bool,
) -> Dict[str, Any]:
    tree_title = payload["hikmah_tree"]["title"]
    incoming_slugs = [lesson["slug"] for lesson in payload["lessons"]]

    existing_tree = _find_tree_by_title(db, tree_title)
    colliding_slugs = _find_colliding_slugs(db, incoming_slugs)

    if not replace:
        problems = []
        if existing_tree is not None:
            problems.append(f"hikmah_trees.title already exists: {tree_title!r} (id={existing_tree.id})")
        if colliding_slugs:
            problems.append(f"lessons.slug already in use: {colliding_slugs}")
        if problems:
            raise RuntimeError(
                "Conflict detected — pass --replace to overwrite:\n  - "
                + "\n  - ".join(problems)
            )
    else:
        # Replacing: delete the tree that matches by title (and its descendants).
        # If a colliding slug belongs to a *different* tree, that's still an
        # error the user has to resolve by hand — refuse to touch it.
        foreign_slugs = []
        if colliding_slugs:
            foreign_lessons = (
                db.query(Lesson.slug, Lesson.hikmah_tree_id)
                .filter(Lesson.slug.in_(colliding_slugs))
                .all()
            )
            for slug, tree_id in foreign_lessons:
                if existing_tree is None or tree_id != existing_tree.id:
                    foreign_slugs.append((slug, tree_id))
        if foreign_slugs:
            raise RuntimeError(
                "Refusing to replace — some incoming slugs belong to a different tree:\n  - "
                + "\n  - ".join(f"{slug!r} (hikmah_tree_id={tid})" for slug, tid in foreign_slugs)
            )

        deleted = _delete_existing_tree(db, tree_title)
        if deleted["trees"]:
            print(
                f"[replace] Deleted existing tree {tree_title!r}: "
                f"{deleted['lessons']} lessons, {deleted['content']} content pages "
                f"(quiz questions/choices cascaded)."
            )

    # Recompute meta.total_pages so it reflects only text-page rows we will insert
    # (quiz entries no longer create their own page row). Leave meta untouched if
    # the input did not declare total_pages. _insert_tree reads tree_data.get("meta")
    # directly, so mutating the dict in place here is enough — no _insert_tree change.
    tree_meta = payload["hikmah_tree"].get("meta")
    if isinstance(tree_meta, dict) and "total_pages" in tree_meta:
        total_text_pages = sum(
            1
            for lesson in payload["lessons"]
            for entry in lesson["content"]
            if entry["content_type"] == "text"
        )
        tree_meta["total_pages"] = total_text_pages

    # Insert fresh tree.
    tree = _insert_tree(db, payload["hikmah_tree"])

    counts = {"lessons": 0, "pages": 0, "questions": 0, "choices": 0}

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

    return {
        "tree_id": tree.id,
        "tree_title": tree.title,
        **counts,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_payload(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upsert a generated hikmah tree JSON file into the database."
    )
    parser.add_argument("input", type=Path, help="Path to <slug>_db.json")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete the existing tree (matched by title) and its descendants before inserting.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse, validate, and exercise the insert path but roll back instead of committing.",
    )
    args = parser.parse_args()

    print(f"Loading {args.input}...")
    payload = _load_payload(args.input)

    print("Validating payload...")
    _validate_payload(payload)

    db = SessionLocal()
    try:
        summary = upsert_hikmah_tree(db, payload, replace=args.replace)

        if args.dry_run:
            db.rollback()
            print("\n[dry-run] Rolled back. Summary of what WOULD have been inserted:")
        else:
            db.commit()
            print("\nCommitted. Summary:")

        print(f"  hikmah_tree.id    = {summary['tree_id']}")
        print(f"  hikmah_tree.title = {summary['tree_title']!r}")
        print(f"  lessons inserted  = {summary['lessons']}")
        print(f"  pages inserted    = {summary['pages']}")
        print(f"  questions inserted= {summary['questions']}")
        print(f"  choices inserted  = {summary['choices']}")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
