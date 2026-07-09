"""Regression tests for PYTHON-FASTAPI-T: LLM omitting gap_summary/citation
on Finding must not raise ValidationError."""
import pytest
from pydantic import ValidationError

from modules.fiqh.sea import Finding, SEAResult, aassess_evidence, _insufficient_fallback


# --- 1. The bug, reproduced at the model layer (no LLM needed) ---

def test_finding_missing_gap_summary_does_not_raise():
    """Exact production payload shape from Sentry: confirmed=False,
    citation='N/A', gap_summary omitted entirely."""
    f = Finding(description="ruling on X", confirmed=False, citation="N/A")
    assert f.gap_summary  # normalized to placeholder, not empty

def test_finding_missing_citation_does_not_raise():
    f = Finding(description="ruling on Y", confirmed=True,
                gap_summary="")
    assert f.citation == ""

def test_searesult_with_partial_finding_parses():
    raw = {
        "findings": [
            {"description": "a", "confirmed": True, "citation": "quoted text", "gap_summary": ""},
            {"description": "b", "confirmed": False, "citation": "N/A"},  # <- the killer
        ],
        "verdict": "INSUFFICIENT",
        "confirmed_facts": ["a"],
        "gaps": ["b"],
    }
    result = SEAResult.model_validate(raw)
    assert result.findings[1].gap_summary != ""


# --- 2. Pipeline-level: ValidationError from LLM must fall back, not retry-storm ---

@pytest.mark.asyncio
async def test_aassess_evidence_validation_error_falls_back(monkeypatch):
    class FakeStructured:
        async def ainvoke(self, _msgs):
            # simulate langchain raising on schema-violating output
            raise ValidationError.from_exception_data("SEAResult", [])
    class FakeModel:
        def with_structured_output(self, _schema):
            return FakeStructured()
    monkeypatch.setattr("modules.fiqh.sea.chat_models.get_sea_model", lambda: FakeModel())

    result = await aassess_evidence("test query", [])
    assert result.verdict == "INSUFFICIENT"
    assert result.gaps == ["test query"]