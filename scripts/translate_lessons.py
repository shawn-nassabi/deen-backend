"""
Offline batch MT job: translate hikmah-tree lessons, lesson content pages, and quiz
questions/choices into the `lesson_translations` Postgres sidecar table (DEE-69),
across the 6 canonical languages.

This is the lesson/quiz/hikmah-tree sibling of `scripts/translate_references_claude_cli.py`
(DEE-67). Source text lives entirely in Postgres (not Pinecone) -- this job enumerates
the 5 source tables directly via SQLAlchemy. It reuses verbatim the claude-CLI
`translate_text()` subprocess logic (`claude -p --model ... --system-prompt ...
--safe-mode --tools "" --no-session-persistence`, non-zero/empty-output handling,
`CLAUDE_TIMEOUT_SECONDS`), so translations run on your authenticated Claude Code
subscription (OAuth) and consume no Anthropic API credits.

This is a re-runnable, idempotent, human-triggered CLI tool -- it is NEVER invoked by
application code, a route, or CI. Idempotency is enforced via `source_hash` (sha256 of
the live source text): an item+language whose stored hash matches the current source
text is skipped; a changed source is re-translated and the row is overwritten via
`Session.merge()`.

Qur'an-preservation disposition (DEE-69 Task 1 finding -- see
`db/models/lesson_translations.py`'s docstring for the full investigation): unlike
DEE-67's `DISABLED_REF_TYPES` structural exclusion, this job has NO reliable per-row
Qur'an marker to key a structural exclusion filter on (`lesson_content.content_type`
is constrained to `{'text','quiz'}` by `scripts/hikmah_generation/upsert_hikmah_tree.py`'s
`VALID_CONTENT_TYPES` validator, has no `tags` column, and embedded Qur'anic verses are
inlined within `content_body`/`explanation` prose rather than isolated in dedicated
rows). Qur'an preservation is therefore enforced SOLELY via the hardened
`TRANSLATION_SYSTEM_PROMPT` below (mechanism 2) -- a documented residual risk, not a
structural guarantee; flagged for the team's coarse offline dev sample-review process
(see memory `dee63-translation-review-workflow`) before enabling any language in
production.

Requirements:
    - The local `claude` CLI must be installed and logged in to your Claude Code
      subscription (verify with a quick `claude -p "hi"`).
    - `DATABASE_URL` must point to a REAL Postgres instance -- source text is read
      from and translations are written to Postgres directly.
    - `alembic upgrade head` must have been run once so the `lesson_translations`
      table exists before this script's writes will succeed.

Usage:
    python scripts/translate_lessons.py --dry-run --limit 5   # preview counts, no CLI/DB writes
    python scripts/translate_lessons.py --entity-type lesson_content --languages urdu --limit 5   # small live sample
    python scripts/translate_lessons.py   # full corpus x all 5 entity types x all 6 languages (only after sampling looks correct)
"""
from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

# Add project root to sys.path (required for local imports)
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.logging_config import setup_logging
from core.utils import source_text_hash
from db.models.hikmah_trees import HikmahTree
from db.models.lesson_content import LessonContent
from db.models.lesson_page_quiz_choices import LessonPageQuizChoice
from db.models.lesson_page_quiz_questions import LessonPageQuizQuestion
from db.models.lesson_translations import LessonTranslation
from db.models.lessons import Lesson
from db.session import SessionLocal

setup_logging()
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #

SUPPORTED_LANGUAGES = ["arabic", "farsi", "urdu", "german", "bahasa melayu", "french"]

# The LOCKED translatable-surfaces table (DEE-69 CONTEXT.md decision 2).
ENTITY_FIELD_MAP = {
    "lesson": (Lesson, ["title", "summary"]),
    "lesson_content": (LessonContent, ["title", "content_body"]),
    "quiz_question": (LessonPageQuizQuestion, ["prompt", "explanation"]),
    "quiz_choice": (LessonPageQuizChoice, ["choice_text"]),
    "hikmah_tree": (HikmahTree, ["title", "summary"]),
}
ENTITY_TYPE_CHOICES = list(ENTITY_FIELD_MAP.keys())

# Model alias passed to `claude --model`. "sonnet" resolves to the latest Sonnet.
# Overridable via --model (accepts an alias like "opus"/"haiku" or a full model id).
DEFAULT_MODEL = "sonnet"

# Per-call wall-clock cap for the `claude` subprocess. Each invocation launches the full
# CLI plus one model turn, so this is generous (matches the reference sample's 10 min).
CLAUDE_TIMEOUT_SECONDS = 600

TRANSLATION_SYSTEM_PROMPT = (
    "You are a faithful, literal translator of Islamic educational lesson and quiz "
    "content for Twelver Shia learners into {language}. "
    "The entire input you receive is the complete and only text to translate; it may "
    "be a title, a short summary, a single sentence, a fragment, or a full multi-"
    "section lesson. Translate exactly what you are given, whatever it is. NEVER ask "
    "for more text, NEVER state that the text is missing, incomplete, or only a "
    "summary/description, NEVER describe or comment on the input, and NEVER output "
    "anything other than the translation itself. If the input is short, your "
    "translation is short. "
    "The input may also be a standalone quiz question or a single answer option that "
    "refers to 'the lesson', 'the text', or a passage that is NOT included with it -- "
    "this is expected and fine. Do NOT ask for that lesson or passage, do NOT attempt "
    "to answer the question, and do NOT assess whether any statement is correct, "
    "complete, or well-formed. Translate the exact words you are given even if they "
    "appear standalone, incomplete, or factually incorrect -- every input is "
    "translatable. "
    "Preserve all meaning, terminology, honorifics, and the Twelver Shia theological "
    "framing of the source text exactly. Do not add interpretation, commentary, "
    "opinion, or fatwa-like guidance of your own. Do not omit or summarize any part "
    "of the text. "
    "Preserve all Markdown formatting (headings, bold, italic, lists, blockquotes) "
    "and any romanized/Latin-script transliterations of Arabic terms (for example "
    "*'adl*, *Usul al-Din*) EXACTLY as they appear in the source -- do NOT convert a "
    "Latin-script transliteration into {language}'s script, and do not alter or drop "
    "the surrounding Markdown markers. "
    "Return ONLY the translated text, with no preamble, explanation, or "
    "additional commentary.\n\n"
    "CRITICAL RELIGIOUS-SENSITIVITY RULE: if the source text contains any Qur'anic "
    "verses (Ayat) quoted in Arabic script, you MUST preserve that Qur'anic Arabic "
    "text EXACTLY character-for-character in its original script -- NEVER translate, "
    "transliterate, paraphrase, or alter it in any way. Translate only the surrounding "
    "prose, explanation, and commentary into {language}. This rule is absolute and "
    "takes priority over completeness of translation.\n\n"
    "The text to translate is provided delimited between the markers <<<BEGIN_SOURCE>>> "
    "and <<<END_SOURCE>>>. Translate ONLY the text between those markers into {language}, "
    "and do NOT include the markers themselves in your output."
)


# ------------------------------------------------------------------ #
# CLI / client setup
# ------------------------------------------------------------------ #

def parse_args(argv=None) -> argparse.Namespace:
    """Parse CLI arguments for the batch translation job."""
    parser = argparse.ArgumentParser(
        description="Batch-translate hikmah-tree lessons/quiz content into "
        "lesson_translations via the local `claude` CLI (Claude Code subscription)"
    )
    parser.add_argument(
        "--languages",
        default=",".join(SUPPORTED_LANGUAGES),
        help="Comma-separated list of target languages (default: all 6 canonical languages)",
    )
    parser.add_argument(
        "--entity-type",
        choices=ENTITY_TYPE_CHOICES + ["all"],
        default="all",
        help="Which entity type to translate (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview counts only; never call the claude CLI or write to the database",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap number of source rows enumerated per entity_type, for sampling",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model passed to `claude --model` and stored in the DB model column "
        f"(default: {DEFAULT_MODEL})",
    )
    return parser.parse_args(argv)


def _resolve_enabled_entity_types(entity_type_arg: str) -> list[str]:
    """Resolve the requested `--entity-type` CLI arg into the enabled subset of
    ENTITY_TYPE_CHOICES.

    Deliberately has no `DISABLED_*` filtering step (unlike
    `translate_references_claude_cli.py`'s `DISABLED_REF_TYPES`), because the Qur'an
    carve-out here operates at the prompt level (mechanism 2, see module docstring),
    not by excluding whole entity types.
    """
    return ENTITY_TYPE_CHOICES if entity_type_arg == "all" else [entity_type_arg]


def _preflight_claude_cli() -> None:
    """Verify the local `claude` CLI is available on PATH before a live run.

    This job constructs NO Anthropic client and reads no API key: translation is
    performed by shelling out to `claude -p`, which authenticates via your Claude Code
    subscription (no API credits are consumed).
    """
    if shutil.which("claude") is None:
        raise RuntimeError(
            "The `claude` CLI was not found on PATH. This batch job translates by shelling "
            "out to the local Claude Code CLI (`claude -p`), which uses your Claude Code "
            "subscription instead of API credits. Install the CLI and log in "
            '(verify with `claude -p "hi"`) before running.'
        )


# ------------------------------------------------------------------ #
# Translation + upsert
# ------------------------------------------------------------------ #

# Conservative refusal/meta-response signatures. These phrases appear ONLY when the model
# declines to translate -- asking for "the lesson"/"the text", apologizing, or editorializing
# on a quiz distractor -- and never inside a faithful translation of lesson/quiz content, so
# a match means the output is not a usable translation and the call is retried (see
# translate_text). Kept multi-word/specific to avoid false positives on legitimate content.
REFUSAL_SIGNATURES = (
    # English
    "i notice this statement", "i should flag", "i cannot translate", "was not provided",
    "not provided to me", "please provide the", "please share the", "i apologize, but",
    "no text was provided", "cannot process this request", "it seems you have",
    # German
    "wurde mir nicht", "liegt mir nicht vor", "bitte teilen sie mir", "bitte senden sie mir",
    "kein text zur übersetzung", "es tut mir leid, aber",
    # French
    "voici la traduction", "il semble que vous", "veuillez fournir", "veuillez me fournir",
    "je ne peux pas traduire",
    # Bahasa Melayu
    "maaf, saya", "maaf, tetapi", "maaf, tiada", "sila berikan teks", "sila kongsikan",
    "tidak dapat memproses", "tidak dapat mengesan", "tiada teks untuk", "tidak diberikan dalam mesej",
    # Farsi / Urdu
    "این متن به نظر می‌رسد", "ارائه نکرده", "لطفاً متن", "گنجانده نشده",
    "معذرت خواہ", "متن درکار", "فراہم نہیں کیا گیا", "فراہم کریں تاکہ", "براہ کرم مکمل",
)

# Re-invoke count when the CLI returns a refusal/meta-response instead of a translation.
# Refusals are non-deterministic, so a couple of retries clears almost all of them.
MAX_TRANSLATION_ATTEMPTS = 4


def _looks_like_refusal(text: str) -> bool:
    """True if `text` matches a known refusal/meta-response signature (not a translation)."""
    low = text.lower()
    return any(sig in low for sig in REFUSAL_SIGNATURES)


def _invoke_claude(*, model: str, text: str, system_prompt: str) -> str:
    """Single `claude -p` invocation. Raises on non-zero exit, timeout, or empty output."""
    result = subprocess.run(
        [
            "claude",
            "-p",
            "--model",
            model,
            # Full-replace system prompt -> a clean literal translator, none of Claude
            # Code's default agentic framing.
            "--system-prompt",
            system_prompt,
            # Skip CLAUDE.md / skills / plugins / hooks (subscription auth stays normal).
            "--safe-mode",
            # Disable all built-in tools -> pure text generation, no tool/permission surface.
            "--tools",
            "",
            "--no-session-persistence",
        ],
        # Delimit the source so the model never mistakes lesson/quiz content (e.g. a
        # question that says "According to the lesson...") for an instruction to answer.
        input=f"<<<BEGIN_SOURCE>>>\n{text}\n<<<END_SOURCE>>>",
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude CLI exited {result.returncode}: {result.stderr.strip()[:500]}"
        )
    translated = result.stdout.strip()
    if not translated:
        raise RuntimeError("claude CLI returned empty output")
    return translated


def translate_text(*, model: str, text: str, language: str) -> str:
    """Translate a single piece of lesson/quiz text into `language` by shelling out to
    the local `claude` CLI in print mode.

    Uses the Claude Code subscription (OAuth), not the Anthropic API -- no API credits are
    consumed. Raises on non-zero exit, timeout, or empty output.

    Guards against the model returning a refusal/meta-response ("please provide the lesson
    text", editorializing on a quiz distractor, etc.) instead of a translation: such output
    is detected via REFUSAL_SIGNATURES and re-attempted up to MAX_TRANSLATION_ATTEMPTS times
    (refusals are flaky). If it still refuses, this raises so the caller logs + skips the
    item (leaving a gap a later re-run fills) rather than committing a non-translation.
    """
    system_prompt = TRANSLATION_SYSTEM_PROMPT.format(language=language)
    translated = ""
    for attempt in range(1, MAX_TRANSLATION_ATTEMPTS + 1):
        translated = _invoke_claude(model=model, text=text, system_prompt=system_prompt)
        if not _looks_like_refusal(translated):
            return translated
        logger.warning(
            "Refusal/meta-response instead of a translation (language=%s, attempt=%d/%d); retrying",
            language, attempt, MAX_TRANSLATION_ATTEMPTS,
        )
    raise RuntimeError(
        f"claude CLI kept returning a refusal after {MAX_TRANSLATION_ATTEMPTS} attempts "
        f"(language={language}): {translated[:150]!r}"
    )


def upsert_translation(
    session_factory,
    *,
    entity_type: str,
    entity_id: int,
    field: str,
    language: str,
    translated_text: str,
    model_name: str,
    source_hash: str,
) -> None:
    """Idempotent upsert of a single translated row, keyed by the composite PK."""
    with session_factory() as db:
        row = LessonTranslation(
            entity_type=entity_type,
            entity_id=entity_id,
            field=field,
            language=language,
            translated_text=translated_text,
            source="mt",
            translated_at=datetime.now(timezone.utc),
            model=model_name,
            source_hash=source_hash,
        )
        db.merge(row)
        db.commit()


# ------------------------------------------------------------------ #
# Corpus enumeration
# ------------------------------------------------------------------ #

def _iter_source_rows(
    session, entity_type: str, *, limit: Optional[int] = None
) -> Iterator[tuple[int, str, str]]:
    """Yield (entity_id, field, text) tuples for every translatable field of every
    source row for `entity_type`, ordered by id, capped at `limit` rows (if given)."""
    model_cls, fields = ENTITY_FIELD_MAP[entity_type]
    query = session.query(model_cls).order_by(model_cls.id.asc())
    if limit is not None:
        query = query.limit(limit)

    for row in query.all():
        for field in fields:
            text = getattr(row, field, None)
            if not text:
                continue
            yield (row.id, field, text)


def _existing_source_hash(
    session, entity_type: str, entity_id: int, field: str, language: str
) -> Optional[str]:
    """Return the stored `source_hash` for an existing translation row, or None if no
    row exists yet."""
    return (
        session.query(LessonTranslation.source_hash)
        .filter(
            LessonTranslation.entity_type == entity_type,
            LessonTranslation.entity_id == entity_id,
            LessonTranslation.field == field,
            LessonTranslation.language == language,
        )
        .scalar()
    )


# ------------------------------------------------------------------ #
# Batch runner
# ------------------------------------------------------------------ #

def run_batch(
    *,
    languages: list[str],
    entity_types: list[str],
    limit: Optional[int],
    dry_run: bool,
    model_name: str,
    session_factory,
) -> dict:
    """Run the batch translation job. Returns a nested summary dict
    {entity_type: {language: count}} of items that were (or, on --dry-run, would be)
    translated. Items already up to date (source_hash matches) are NOT counted. One
    bad item/language never aborts the whole run.

    Unlike the Pinecone-sourced reference script, `--dry-run` here still performs real
    (read-only) Postgres queries to enumerate rows and check staleness -- Postgres IS
    the source, so a dry-run with zero DB reads is not possible; only `translate_text`
    (claude CLI) and `upsert_translation` (writes) are skipped.
    """
    summary: dict[str, dict[str, int]] = {
        entity_type: {lang: 0 for lang in languages} for entity_type in entity_types
    }

    for entity_type in entity_types:
        with session_factory() as session:
            for entity_id, field, text in _iter_source_rows(session, entity_type, limit=limit):
                computed_hash = source_text_hash(text)

                for language in languages:
                    try:
                        existing_hash = _existing_source_hash(
                            session, entity_type, entity_id, field, language
                        )
                        if existing_hash == computed_hash:
                            continue

                        summary[entity_type][language] += 1
                        if dry_run:
                            continue

                        translated = translate_text(model=model_name, text=text, language=language)
                        upsert_translation(
                            session_factory,
                            entity_type=entity_type,
                            entity_id=entity_id,
                            field=field,
                            language=language,
                            translated_text=translated,
                            model_name=model_name,
                            source_hash=computed_hash,
                        )
                    except Exception:
                        logger.error(
                            "Failed to translate/upsert entity_type=%s entity_id=%s field=%s language=%s",
                            entity_type,
                            entity_id,
                            field,
                            language,
                            exc_info=True,
                        )

    return summary


def main() -> None:
    args = parse_args()
    languages = [lang.strip().lower() for lang in args.languages.split(",") if lang.strip()]
    entity_types = _resolve_enabled_entity_types(args.entity_type)

    if not args.dry_run:
        _preflight_claude_cli()

    summary = run_batch(
        languages=languages,
        entity_types=entity_types,
        limit=args.limit,
        dry_run=args.dry_run,
        model_name=args.model,
        session_factory=SessionLocal,
    )
    logger.info("Batch complete: %s", summary)


if __name__ == "__main__":
    main()
