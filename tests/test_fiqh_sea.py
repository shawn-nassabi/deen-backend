"""Unit tests for modules/fiqh/sea.py — all LLM calls are mocked."""
from __future__ import annotations
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import patch, MagicMock
from modules.fiqh.sea import assess_evidence, SEAResult, Finding


def _mock_sea_model(return_value):
    """Helper: create a mock model whose with_structured_output chain returns return_value."""
    mock_model = MagicMock()
    mock_structured = MagicMock()
    mock_model.with_structured_output.return_value = mock_structured
    mock_structured.invoke.return_value = return_value
    return mock_model


def _make_doc(chunk_id: str) -> dict:
    """Helper: create a minimal doc dict with the given chunk_id."""
    return {
        "chunk_id": chunk_id,
        "metadata": {
            "source_book": "Islamic Laws",
            "chapter": "Ch1",
            "section": "S1",
            "ruling_number": "001",
            "text_en": f"text for {chunk_id}",
        },
        "page_content": f"text for {chunk_id}",
    }


class TestSEAModels:
    def test_finding_is_valid_pydantic_model(self):
        """Finding can be instantiated with required fields."""
        f = Finding(
            description="Is wudu required before salah?",
            confirmed=True,
            citation="Wudu is obligatory before prayer.",
            gap_summary="",
        )
        assert f.description == "Is wudu required before salah?"
        assert f.confirmed is True
        assert f.citation == "Wudu is obligatory before prayer."
        assert f.gap_summary == ""

    def test_finding_unconfirmed_has_empty_citation(self):
        """Unconfirmed Finding should have empty citation and non-empty gap_summary."""
        f = Finding(
            description="What is the ruling on salah during travel?",
            confirmed=False,
            citation="",
            gap_summary="No ruling found about travel prayer shortening.",
        )
        assert f.confirmed is False
        assert f.citation == ""
        assert f.gap_summary != ""

    def test_searesult_is_valid_pydantic_model_sufficient(self):
        """SEAResult with SUFFICIENT verdict can be instantiated."""
        result = SEAResult(
            findings=[
                Finding(
                    description="Is pork haram?",
                    confirmed=True,
                    citation="Pork is haram.",
                    gap_summary="",
                )
            ],
            verdict="SUFFICIENT",
            confirmed_facts=["Pork is haram per Sistani's ruling."],
            gaps=[],
        )
        assert result.verdict == "SUFFICIENT"
        assert len(result.confirmed_facts) == 1
        assert result.gaps == []

    def test_searesult_is_valid_pydantic_model_insufficient(self):
        """SEAResult with INSUFFICIENT verdict can be instantiated."""
        result = SEAResult(
            findings=[],
            verdict="INSUFFICIENT",
            confirmed_facts=[],
            gaps=["No ruling found for query."],
        )
        assert result.verdict == "INSUFFICIENT"
        assert len(result.gaps) == 1

    def test_searesult_verdict_rejects_invalid_literal(self):
        """SEAResult.verdict only accepts 'SUFFICIENT' or 'INSUFFICIENT'."""
        with pytest.raises(Exception):
            SEAResult(
                findings=[],
                verdict="MAYBE",  # type: ignore[arg-type]
                confirmed_facts=[],
                gaps=[],
            )


class TestAssessEvidence:
    def test_returns_structured_result_on_success(self):
        """assess_evidence passes through a complete SEAResult from the LLM."""
        expected = SEAResult(
            findings=[
                Finding(
                    description="Is wudu required before salah?",
                    confirmed=True,
                    citation="Wudu is required before salah.",
                    gap_summary="",
                )
            ],
            verdict="SUFFICIENT",
            confirmed_facts=["Wudu is required before salah."],
            gaps=[],
        )
        with patch(
            "modules.fiqh.sea.chat_models.get_sea_model",
            return_value=_mock_sea_model(expected),
        ):
            result = assess_evidence("Is wudu required?", [_make_doc("chunk_1")])
        assert result is expected

    def test_returns_fallback_on_llm_exception(self):
        """assess_evidence returns INSUFFICIENT fallback when LLM raises."""
        mock_model = MagicMock()
        mock_structured = MagicMock()
        mock_model.with_structured_output.return_value = mock_structured
        mock_structured.invoke.side_effect = Exception("API failure")

        with patch(
            "modules.fiqh.sea.chat_models.get_sea_model",
            return_value=mock_model,
        ):
            result = assess_evidence("Is wudu required?", [_make_doc("chunk_1")])

        assert result.verdict == "INSUFFICIENT"
        assert result.findings == []
        assert result.confirmed_facts == []
        assert "Is wudu required?" in result.gaps

    def test_fallback_contains_query_in_gaps(self):
        """Fallback SEAResult has the original query in gaps list."""
        query = "What breaks my wudu?"
        mock_model = MagicMock()
        mock_structured = MagicMock()
        mock_model.with_structured_output.return_value = mock_structured
        mock_structured.invoke.side_effect = RuntimeError("network error")

        with patch(
            "modules.fiqh.sea.chat_models.get_sea_model",
            return_value=mock_model,
        ):
            result = assess_evidence(query, [_make_doc("chunk_1")])

        assert query in result.gaps

    def test_empty_docs_returns_fallback_no_crash(self):
        """assess_evidence with empty docs list does not crash — returns fallback."""
        mock_model = MagicMock()
        mock_structured = MagicMock()
        mock_model.with_structured_output.return_value = mock_structured
        mock_structured.invoke.side_effect = Exception("no docs")

        with patch(
            "modules.fiqh.sea.chat_models.get_sea_model",
            return_value=mock_model,
        ):
            result = assess_evidence("test query", [])

        assert isinstance(result, SEAResult)
        assert result.verdict == "INSUFFICIENT"

    def test_uses_with_structured_output(self):
        """assess_evidence calls model.with_structured_output(SEAResult)."""
        expected = SEAResult(
            findings=[],
            verdict="INSUFFICIENT",
            confirmed_facts=[],
            gaps=["gap"],
        )
        mock_model = MagicMock()
        mock_structured = MagicMock()
        mock_model.with_structured_output.return_value = mock_structured
        mock_structured.invoke.return_value = expected

        with patch(
            "modules.fiqh.sea.chat_models.get_sea_model",
            return_value=mock_model,
        ):
            assess_evidence("test query", [_make_doc("chunk_1")])

        # Verify with_structured_output was called with SEAResult
        mock_model.with_structured_output.assert_called_once_with(SEAResult)

    def test_sufficient_verdict_when_all_findings_confirmed(self):
        """SUFFICIENT verdict is valid when all findings are confirmed."""
        sufficient_result = SEAResult(
            findings=[
                Finding(
                    description="finding 1",
                    confirmed=True,
                    citation="quote 1",
                    gap_summary="",
                ),
                Finding(
                    description="finding 2",
                    confirmed=True,
                    citation="quote 2",
                    gap_summary="",
                ),
            ],
            verdict="SUFFICIENT",
            confirmed_facts=["fact 1", "fact 2"],
            gaps=[],
        )
        with patch(
            "modules.fiqh.sea.chat_models.get_sea_model",
            return_value=_mock_sea_model(sufficient_result),
        ):
            result = assess_evidence("complex query", [_make_doc("chunk_1")])
        assert result.verdict == "SUFFICIENT"
        assert all(f.confirmed for f in result.findings)

    def test_insufficient_verdict_when_any_finding_unconfirmed(self):
        """INSUFFICIENT verdict is valid when any finding is unconfirmed."""
        insufficient_result = SEAResult(
            findings=[
                Finding(
                    description="finding 1",
                    confirmed=True,
                    citation="quote 1",
                    gap_summary="",
                ),
                Finding(
                    description="finding 2",
                    confirmed=False,
                    citation="",
                    gap_summary="no ruling found",
                ),
            ],
            verdict="INSUFFICIENT",
            confirmed_facts=["fact 1"],
            gaps=["no ruling for finding 2"],
        )
        with patch(
            "modules.fiqh.sea.chat_models.get_sea_model",
            return_value=_mock_sea_model(insufficient_result),
        ):
            result = assess_evidence("multi-part query", [_make_doc("chunk_1")])
        assert result.verdict == "INSUFFICIENT"
        assert len(result.gaps) >= 1

    def test_never_raises(self):
        """assess_evidence must never raise under any condition."""
        mock_model = MagicMock()
        mock_model.with_structured_output.side_effect = Exception("unexpected error")

        with patch(
            "modules.fiqh.sea.chat_models.get_sea_model",
            return_value=mock_model,
        ):
            # Must not raise
            result = assess_evidence("any query", [_make_doc("chunk_1")])
        assert isinstance(result, SEAResult)
        assert result.verdict == "INSUFFICIENT"
