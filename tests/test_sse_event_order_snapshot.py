"""
DEE-46 / Phase 7: SSE event-order snapshot gate.

Programmatic equivalent of "open two simultaneous curl shells and visually
inspect the event order." Uses syrupy to compare the *event-type sequence*
emitted by the agentic streaming pipeline against a committed snapshot.

We snapshot only event types (not data payloads) so the gate stays stable
across legitimate copy / token / reference changes but trips the moment a
refactor accidentally drops, reorders, or duplicates an event.

Run:
    pytest tests/test_sse_event_order_snapshot.py -q
    pytest tests/test_sse_event_order_snapshot.py -q --snapshot-update    # to refresh
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import List

import pytest

from tests.conftest_async_stubs import (
    StubConfig,
    install_pipeline_stubs,
    run_pipeline_once,
)


# --- helpers ---------------------------------------------------------------- #


def _decode(chunks) -> str:
    parts: List[str] = []
    for ch in chunks:
        if isinstance(ch, bytes):
            ch = ch.decode("utf-8", errors="ignore")
        parts.append(str(ch))
    return "".join(parts)


def _event_type_sequence(sse_text: str) -> List[str]:
    """Return ordered list of `event:` types emitted across the stream."""
    types: List[str] = []
    for raw_event in re.split(r"\n\n+", sse_text):
        if not raw_event.strip():
            continue
        for line in raw_event.split("\n"):
            if line.startswith("event:"):
                types.append(line[6:].strip())
                break
    return types


def _event_type_with_status_step_sequence(sse_text: str) -> List[str]:
    """Like `_event_type_sequence` but enriches `status` events with the
    `step` field from their JSON payload — produces e.g. `status:agent`,
    `status:retrieve_shia_documents_tool`, etc. so reordering or deletion
    of any specific status step is caught, while individual response_chunk
    tokens stay collapsed."""
    out: List[str] = []
    for raw_event in re.split(r"\n\n+", sse_text):
        if not raw_event.strip():
            continue
        event_type = None
        data_lines: List[str] = []
        for line in raw_event.split("\n"):
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if event_type is None:
            continue
        if event_type == "status" and data_lines:
            try:
                payload = json.loads("\n".join(data_lines))
                step = payload.get("step")
                if step:
                    out.append(f"status:{step}")
                    continue
            except json.JSONDecodeError:
                pass
        out.append(event_type)
    return out


# --- gates ------------------------------------------------------------------ #


def test_hadith_path_event_type_sequence_matches_snapshot(snapshot):
    """Lock the SSE event-type sequence for the hadith (non-fiqh) agentic path."""
    cfg = StubConfig()
    with install_pipeline_stubs(cfg):
        # Warmup so the first measured run is steady-state.
        asyncio.run(run_pipeline_once())
        elapsed, chunks = asyncio.run(run_pipeline_once(session_id="hadith-snapshot"))

    sse_text = _decode(chunks)
    enriched = _event_type_with_status_step_sequence(sse_text)
    # Collapse runs of identical event types (each response_chunk token would
    # otherwise produce a separate entry; we already collapse status:step).
    collapsed: List[str] = []
    for et in enriched:
        if not collapsed or collapsed[-1] != et:
            collapsed.append(et)

    assert collapsed == snapshot


def test_hadith_path_response_chunks_present_and_non_empty():
    """Belt-and-braces: even if the snapshot drift gets approved, this
    asserts the pipeline still emits at least one token per request."""
    cfg = StubConfig()
    with install_pipeline_stubs(cfg):
        asyncio.run(run_pipeline_once())
        elapsed, chunks = asyncio.run(run_pipeline_once(session_id="hadith-tokens"))

    sse_text = _decode(chunks)
    types = _event_type_sequence(sse_text)
    response_chunk_count = sum(1 for t in types if t == "response_chunk")
    assert response_chunk_count >= 1, (
        f"hadith path emitted no `response_chunk` events. Sequence was: {types}"
    )


def test_hadith_path_terminates_with_done_event():
    """The frontend treats `event: done` as the close signal; verify it
    arrives after every other event (no early termination, no missing tail)."""
    cfg = StubConfig()
    with install_pipeline_stubs(cfg):
        asyncio.run(run_pipeline_once())
        elapsed, chunks = asyncio.run(run_pipeline_once(session_id="hadith-done"))

    sse_text = _decode(chunks)
    types = _event_type_sequence(sse_text)
    assert types, "no SSE events emitted"
    assert types[-1] == "done", (
        f"hadith path did not terminate with `event: done`. Last event: "
        f"{types[-1]!r}. Full sequence: {types}"
    )


# --- fiqh path note --------------------------------------------------------- #
# The shared `installed_stubs` fixture forces the fiqh classifier to return
# OUT_OF_SCOPE_FIQH so the fiqh sub-graph is never invoked from the
# concurrency / Sentry stubs (which is what those tests want).
#
# A fiqh-path SSE snapshot would need a different stub configuration that
# forces `IN_SCOPE_FIQH` and provides canned fiqh retrieval / SEA results.
# Adding that fixture is a meaningful extension to conftest_async_stubs and
# is captured as a follow-up in the DEE-46 PR description rather than in
# scope here. The hadith path snapshot covers the main agentic flow plus
# the early-exit and tool-orchestration logic shared with the fiqh path.
