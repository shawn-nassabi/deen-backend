"""
Token-cost DEE-60 Phase 2 tests (payload diet).

Covers:
- Metadata whitelists at the reranker/retriever boundary (compressed
  text blobs never leave retrieval) with a byte-identical regression on the
  frontend reference JSON.
- Compact ToolMessage rewrite (planner view; full docs stay in state;
  ensure_ascii=False; TOOLMSG_COMPACT=0 kill-switch).
- History budgets (count + char caps, pair alignment, HISTORY_BUDGETS=0
  kill-switch) and the classifier context default.
- Slimmed compact_format_references scaffold + Quran text caps.
"""

from __future__ import annotations

import inspect
import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agents.core.chat_agent import ChatAgent
from core import utils
from core.history_budget import budget_messages
from modules.reranking.reranker import HADITH_METADATA_WHITELIST, _whitelist_metadata
from modules.retrieval.retriever import _whitelist_quran_metadata


RAW_HADITH_MD = {
    "author": "Al-Kulayni",
    "volume": "2",
    "book_number": "1",
    "book_title": "Al-Kafi",
    "chapter_number": "53",
    "chapter_title": "Patience",
    "collection": "Al-Kafi",
    "grade_ar": "صحيح",
    "grade_en": "Sahih",
    "hadith_id": "h-123",
    "hadith_no": "10",
    "hadith_url": "https://example.com/h-123",
    "lang": "en",
    "sect": "shia",
    "reference": "Al-Kafi V2 B1 C53 H10",
    # compressed duplicates that must be dropped
    "text_en": "H4sIAAAAAAAA_base64gzipblob",
    "text_ar": "H4sIAAAAAAAA_base64gzipblob_ar",
}

RAW_QURAN_MD = {
    "surah_name": "Al-Baqarah",
    "title": "The Cow",
    "chapter_number": "2",
    "verses_covered": "153-157",
    "starting_verse": "153",
    "ending_verse": "157",
    "author": "Allamah Tabatabai",
    "collection": "Al-Mizan",
    "volume": "2",
    "sect": "shia",
    "Type": "Tafsir",
    # compressed duplicates that must be dropped
    "text_chunk": "H4sIAAAAAAAA_tafsir_blob",
    "english_quran_translation": "H4sIAAAAAAAA_translation_blob",
}


def _hadith_doc(md):
    return {
        "hadith_id": "h-123",
        "metadata": md,
        "page_content_en": "Indeed, patience is half of faith.",
        "page_content_ar": "الصبر نصف الإيمان",
    }


def _quran_doc(md):
    return {
        "chunk_id": "q-1",
        "metadata": md,
        "page_content_en": "Tafsir commentary text.",
        "quran_translation": "Seek help through patience and prayer.",
    }


# ---------------------------------------------------------------------------
# Metadata whitelists
# ---------------------------------------------------------------------------


def test_hadith_whitelist_drops_blobs_keeps_citation_fields():
    clean = _whitelist_metadata(RAW_HADITH_MD)
    assert "text_en" not in clean and "text_ar" not in clean
    assert set(clean) == set(HADITH_METADATA_WHITELIST)
    assert clean["book_title"] == "Al-Kafi"
    assert _whitelist_metadata(None) == {}


def test_quran_whitelist_drops_blobs_keeps_grouping_type():
    clean = _whitelist_quran_metadata(RAW_QURAN_MD)
    assert "text_chunk" not in clean
    assert "english_quran_translation" not in clean
    assert clean["starting_verse"] == "153" and clean["ending_verse"] == "157"
    # Grouping in compact_format_references keys off Type / surah_name
    assert utils._is_quran_doc(clean)


def test_frontend_reference_json_byte_identical_after_whitelist():
    """The hadith_references / quran_references SSE payloads must be
    unchanged by the whitelist — every field they read survives."""
    raw = utils.format_references_as_json([_hadith_doc(RAW_HADITH_MD)])
    clean = utils.format_references_as_json([_hadith_doc(_whitelist_metadata(RAW_HADITH_MD))])
    assert json.dumps(raw, sort_keys=True) == json.dumps(clean, sort_keys=True)

    raw_q = utils.format_quran_references_as_json([_quran_doc(RAW_QURAN_MD)])
    clean_q = utils.format_quran_references_as_json(
        [_quran_doc(_whitelist_quran_metadata(RAW_QURAN_MD))]
    )
    assert json.dumps(raw_q, sort_keys=True) == json.dumps(clean_q, sort_keys=True)


# ---------------------------------------------------------------------------
# Compact ToolMessage rewrite
# ---------------------------------------------------------------------------


def _tool_message_and_result():
    result_data = {
        "documents": [_hadith_doc(_whitelist_metadata(RAW_HADITH_MD))],
        "count": 1,
        "source": "shia",
        "query_used": "patience",
    }
    message = ToolMessage(
        content=json.dumps(result_data),
        name="retrieve_shia_documents_tool",
        tool_call_id="tc-1",
    )
    return message, result_data


def test_compact_tool_message_rewrites_planner_view(monkeypatch):
    monkeypatch.delenv("TOOLMSG_COMPACT", raising=False)
    message, result_data = _tool_message_and_result()
    ChatAgent._compact_tool_message(message, result_data)

    payload = json.loads(message.content)
    assert payload["source"] == "shia" and payload["count"] == 1
    doc = payload["documents"][0]
    assert doc["id"] == "h-123"
    assert doc["title"] == "Al-Kafi"
    assert doc["snippet"].startswith("Indeed, patience")
    # Compact view carries no Arabic body and no full metadata
    assert "page_content_ar" not in message.content
    assert "grade_ar" not in message.content
    # Full docs in result_data (the state source) are untouched
    assert result_data["documents"][0]["page_content_ar"] == "الصبر نصف الإيمان"


def test_compact_tool_message_uses_raw_unicode(monkeypatch):
    monkeypatch.delenv("TOOLMSG_COMPACT", raising=False)
    message, result_data = _tool_message_and_result()
    result_data["documents"][0]["page_content_en"] = "قال الإمام: الصبر نصف الإيمان"
    ChatAgent._compact_tool_message(message, result_data)
    # ensure_ascii=False: Arabic must not be \uXXXX-inflated
    assert "الصبر" in message.content
    assert "\\u" not in message.content


def test_compact_tool_message_kill_switch(monkeypatch):
    monkeypatch.setenv("TOOLMSG_COMPACT", "0")
    message, result_data = _tool_message_and_result()
    original = message.content
    ChatAgent._compact_tool_message(message, result_data)
    assert message.content == original


# ---------------------------------------------------------------------------
# History budgets
# ---------------------------------------------------------------------------


def _turns(n_pairs, chars=100):
    msgs = []
    for i in range(n_pairs):
        msgs.append(HumanMessage(content=f"q{i} " + "x" * chars))
        msgs.append(AIMessage(content=f"a{i} " + "y" * chars))
    return msgs


def test_budget_caps_message_count(monkeypatch):
    monkeypatch.delenv("HISTORY_BUDGETS", raising=False)
    msgs = _turns(15)  # 30 messages
    kept = budget_messages(msgs, 10, 100000)
    assert len(kept) == 10
    assert kept[-1] is msgs[-1]
    assert isinstance(kept[0], HumanMessage)


def test_budget_caps_chars_and_keeps_freshest_turn(monkeypatch):
    monkeypatch.delenv("HISTORY_BUDGETS", raising=False)
    msgs = _turns(5, chars=2000)  # each message > 2000 chars
    kept = budget_messages(msgs, 10, 5000)
    assert 2 <= len(kept) <= 3
    assert kept[-1] is msgs[-1]


def test_budget_drops_orphan_ai_head(monkeypatch):
    monkeypatch.delenv("HISTORY_BUDGETS", raising=False)
    msgs = _turns(6)
    kept = budget_messages(msgs, 5, 100000)  # odd cap would start on an AIMessage
    assert isinstance(kept[0], HumanMessage)


def test_budget_kill_switch_passthrough(monkeypatch):
    monkeypatch.setenv("HISTORY_BUDGETS", "0")
    msgs = _turns(15)
    assert budget_messages(msgs, 4, 10) == msgs


def test_classifier_context_default_is_4():
    from modules.context.context import get_recent_context

    assert inspect.signature(get_recent_context).parameters["max_messages"].default == 4


# ---------------------------------------------------------------------------
# Slimmed reference scaffold
# ---------------------------------------------------------------------------


def test_compact_hadith_block_drops_noise_keeps_citation_fields():
    text = utils.compact_format_references([_hadith_doc(_whitelist_metadata(RAW_HADITH_MD))])
    assert "**Book Title:** Al-Kafi" in text
    assert "**Hadith Number:** 10" in text
    assert "**Grade:** Sahih" in text
    for dropped in ("Hadith ID", "URL", "Language", "Grade (AR)"):
        assert dropped not in text
    assert "--------------------------------------" not in text  # short separators now


def test_compact_quran_block_caps_combined_text():
    doc = _quran_doc(_whitelist_quran_metadata(RAW_QURAN_MD))
    doc["quran_translation"] = "v" * 5000
    doc["page_content_en"] = "t" * 5000
    text = utils.compact_format_references([doc])
    # translation capped at 900, tafsir at 1300 (+ "...." markers)
    assert "v" * 900 in text and "v" * 901 not in text
    assert "t" * 1300 in text and "t" * 1301 not in text
