"""
tests/test_fiqh_graph_logging.py

Unit tests for structured logging in agents/fiqh/fiqh_graph.py.
Tests that WARNING events fire at the correct FAIR-RAG failure boundaries.

NOTE: Patch targets point to the SOURCE module namespace, not fiqh_graph's namespace.
This works because each node function uses a deferred `from ... import X` on every call,
which re-binds the local name to the patched object each time the node runs.
WARNING: If these deferred imports are ever hoisted to module-level in fiqh_graph.py,
patch targets must change to "agents.fiqh.fiqh_graph.retrieve_fiqh_documents" etc.
"""
import logging
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.fiqh.fiqh_graph import _retrieve_node, _filter_node, _route_after_assess


LOGGER_NAME = "agents.fiqh.fiqh_graph"


# --------------------------------------------------------------------------- #
# FIQH-02: Zero-doc retrieval WARNING
# --------------------------------------------------------------------------- #

def test_fiqh02_warning_on_zero_docs(caplog):
    """WARNING logged when retrieve_fiqh_documents returns empty list."""
    state = {
        "query": "test query", "iteration": 0, "accumulated_docs": [],
        "prior_queries": ["test query"], "sea_result": None,
        "verdict": "INSUFFICIENT", "status_events": [],
    }
    with patch("modules.fiqh.retriever.retrieve_fiqh_documents", return_value=[]):
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            _retrieve_node(state)
    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("zero documents" in m for m in warning_msgs), \
        f"Expected 'zero documents' WARNING, got: {warning_msgs}"


def test_fiqh02_no_warning_when_docs_returned(caplog):
    """No WARNING logged when retrieve_fiqh_documents returns documents."""
    state = {
        "query": "test query", "iteration": 0, "accumulated_docs": [],
        "prior_queries": ["test query"], "sea_result": None,
        "verdict": "INSUFFICIENT", "status_events": [],
    }
    mock_docs = [{"chunk_id": "c1", "text": "some fiqh ruling"}]
    with patch("modules.fiqh.retriever.retrieve_fiqh_documents", return_value=mock_docs):
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            _retrieve_node(state)
    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("zero documents" in m for m in warning_msgs), \
        f"Unexpected 'zero documents' WARNING: {warning_msgs}"


# --------------------------------------------------------------------------- #
# FIQH-03: Filter drops all docs WARNING
# --------------------------------------------------------------------------- #

def test_fiqh03_warning_on_empty_filter(caplog):
    """WARNING logged when filter_evidence returns empty list."""
    state = {
        "query": "test query", "iteration": 1,
        "accumulated_docs": [{"chunk_id": "c1", "text": "doc"}],
        "prior_queries": ["test query"], "sea_result": None,
        "verdict": "INSUFFICIENT", "status_events": [],
    }
    with patch("modules.fiqh.filter.filter_evidence", return_value=[]):
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            _filter_node(state)
    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("filter removed all documents" in m for m in warning_msgs), \
        f"Expected 'filter removed all documents' WARNING, got: {warning_msgs}"


def test_fiqh03_no_warning_when_docs_pass(caplog):
    """No WARNING logged when filter_evidence returns documents."""
    state = {
        "query": "test query", "iteration": 1,
        "accumulated_docs": [{"chunk_id": "c1", "text": "doc"}],
        "prior_queries": ["test query"], "sea_result": None,
        "verdict": "INSUFFICIENT", "status_events": [],
    }
    filtered_docs = [{"chunk_id": "c1", "text": "doc"}]
    with patch("modules.fiqh.filter.filter_evidence", return_value=filtered_docs):
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            _filter_node(state)
    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("filter removed all documents" in m for m in warning_msgs), \
        f"Unexpected filter WARNING: {warning_msgs}"


# --------------------------------------------------------------------------- #
# FIQH-04: Max iterations + INSUFFICIENT WARNING
# --------------------------------------------------------------------------- #

def test_fiqh04_warning_on_max_iterations_insufficient(caplog):
    """WARNING logged when iteration=3 and verdict=INSUFFICIENT."""
    state = {
        "query": "test", "iteration": 3, "accumulated_docs": [],
        "prior_queries": [], "sea_result": None,
        "verdict": "INSUFFICIENT", "status_events": [],
    }
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        result = _route_after_assess(state)
    assert result == "exit"
    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("exhausted max iterations" in m for m in warning_msgs), \
        f"Expected 'exhausted max iterations' WARNING, got: {warning_msgs}"


def test_fiqh04_no_warning_on_sufficient_exit(caplog):
    """No WARNING logged when verdict=SUFFICIENT (even at iteration=3)."""
    state = {
        "query": "test", "iteration": 3, "accumulated_docs": [],
        "prior_queries": [], "sea_result": None,
        "verdict": "SUFFICIENT", "status_events": [],
    }
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        result = _route_after_assess(state)
    assert result == "exit"
    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("exhausted max iterations" in m for m in warning_msgs), \
        f"Unexpected WARNING on SUFFICIENT exit: {warning_msgs}"


def test_fiqh04_no_warning_before_max_iterations(caplog):
    """No WARNING and route is 'refine' when iteration=2 and verdict=INSUFFICIENT."""
    state = {
        "query": "test", "iteration": 2, "accumulated_docs": [],
        "prior_queries": [], "sea_result": None,
        "verdict": "INSUFFICIENT", "status_events": [],
    }
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        result = _route_after_assess(state)
    assert result == "refine"
    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("exhausted max iterations" in m for m in warning_msgs), \
        f"Unexpected WARNING at mid-loop: {warning_msgs}"
