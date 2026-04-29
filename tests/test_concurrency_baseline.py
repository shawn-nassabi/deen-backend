"""
Phase 0 (DEE-39) concurrency baseline.

Runs N=10 concurrent agentic pipeline calls against the stubbed in-process
pipeline (see tests/conftest_async_stubs.py). Captures wall-clock, p50, p95,
and the inferred speedup vs. an idealised fully-serialised run with the same
stub latencies.

Two gates here:

1. `test_baseline_records_snapshot` always runs and writes a JSON snapshot
   to documentation/async_baseline.md. Never asserts on latency — this is
   the BEFORE picture for later phases to compare against.

2. `test_concurrency_threshold` asserts wall-clock < per_request_latency *
   1.5 — i.e. N concurrent requests finish in roughly the time of a single
   request. langgraph already yields between sync nodes so Phase 0 sits at
   ~4.5x and fails this gate; Phase 2/3 (async nodes + async modules) is
   where the ratio drops below 1.5x. Marked `xfail(strict=True)` so the
   migration is forced to flip it to passing and drop the marker.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from scripts.loadtest_agentic import _emit_snapshot, _run_in_process, parse_args


_BASELINE_PATH = Path(__file__).resolve().parent.parent / "documentation" / "async_baseline.md"


def _build_args(n: int, label: str):
    # Reuse the loadtest's argparse so the test exercises the exact same code
    # the CLI does — no second source of truth for stub latencies.
    return parse_args(
        [
            "--mode",
            "in-process",
            "--n",
            str(n),
            "--label",
            label,
        ]
    )


@pytest.mark.asyncio
async def test_baseline_records_snapshot():
    """Always runs — emits the Phase 0 snapshot to documentation/async_baseline.md."""
    label = os.environ.get("ASYNC_BASELINE_LABEL", "phase-0 baseline (DEE-39)")
    args = _build_args(n=10, label=label)
    payload = await _run_in_process(args)

    assert payload["n"] == 10
    assert payload["wall_clock_s"] > 0
    assert payload["p50_s"] > 0
    assert len(payload["stubs"]) > 0

    _emit_snapshot(_BASELINE_PATH, payload)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Real concurrency gate: wall-clock should approach single-request latency. "
        "Phase 0 is ~4.5x because the agent's sync nodes / chain.stream / sync "
        "Pinecone serialise on the event loop. Phase 2 (DEE-41) async nodes and "
        "Phase 3 (DEE-42) async modules are where the ratio drops below 1.5x; "
        "remove this marker once it XPASSes."
    ),
)
@pytest.mark.asyncio
async def test_concurrency_threshold():
    """Wall-clock < per_request * 1.5 — N requests should finish in ~one-request-time."""
    args = _build_args(n=10, label="phase-0 threshold-check")
    payload = await _run_in_process(args)

    expected_per_request = payload["stubs"]["expected_per_request_s"]
    threshold = expected_per_request * 1.5
    ratio = payload["wall_clock_s"] / expected_per_request
    assert payload["wall_clock_s"] < threshold, (
        f"wall_clock={payload['wall_clock_s']}s vs threshold={threshold:.3f}s "
        f"(per_request={expected_per_request}s, ratio={ratio:.2f}x — "
        f"need <1.5x for real concurrency)"
    )
