"""
Unit tests for the real-time fiqh SSE status mechanism (260509-3cd).

These tests cover the small queue helper in core.context that fiqh
sub-graph nodes use to push status events to the SSE pipeline. Full
end-to-end SSE order coverage lives in tests/test_agentic_streaming_sse.py
(which skips gracefully when the env can't bootstrap the pipeline).
"""
from __future__ import annotations

import asyncio

import pytest

from core.context import _push_fiqh_status, fiqh_status_queue


@pytest.mark.asyncio
async def test_push_fiqh_status_writes_to_queue():
    queue: asyncio.Queue = asyncio.Queue()
    token = fiqh_status_queue.set(queue)
    try:
        _push_fiqh_status("fiqh_decompose", "Decomposing fiqh query...")
    finally:
        fiqh_status_queue.reset(token)

    assert queue.qsize() == 1
    item = queue.get_nowait()
    assert item == {"step": "fiqh_decompose", "message": "Decomposing fiqh query..."}


@pytest.mark.asyncio
async def test_push_fiqh_status_noop_when_unset():
    # Default contextvar value is None — calling the helper must be a silent
    # no-op (sub-graph nodes are also reachable from non-streaming code paths
    # like the legacy pipeline and direct .ainvoke callers).
    assert fiqh_status_queue.get() is None
    _push_fiqh_status("anything", "anything")  # must not raise


@pytest.mark.asyncio
async def test_push_fiqh_status_swallows_full_queue_errors():
    # Bounded queue at capacity; put_nowait raises QueueFull. Helper must
    # swallow the error so a transient queue-overflow can never abort the
    # sub-graph itself.
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    queue.put_nowait("placeholder")
    assert queue.full()

    token = fiqh_status_queue.set(queue)
    try:
        _push_fiqh_status("fiqh_decompose", "should be dropped")
    finally:
        fiqh_status_queue.reset(token)

    # Queue still contains only the placeholder; helper did not raise.
    assert queue.qsize() == 1
    assert queue.get_nowait() == "placeholder"
