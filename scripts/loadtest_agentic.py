"""
Concurrency loadtest for the agentic streaming pipeline (DEE-36).

Defaults to in-process mode: drives core.pipeline_langgraph.chat_pipeline_streaming_agentic
directly with the deterministic stubs from tests.conftest_async_stubs. No
Anthropic / Pinecone / Redis credentials required, no FastAPI HTTP layer
involved — what we measure is event-loop concurrency through the pipeline
itself, which is exactly the surface DEE-36 is converting to async.

Run:
    python scripts/loadtest_agentic.py --n 10
    python scripts/loadtest_agentic.py --n 10 --emit-snapshot documentation/async_baseline.md
    python scripts/loadtest_agentic.py --n 10 --label "phase-0 baseline"

`--mode external --url http://127.0.0.1:8000` is reserved for ad-hoc smoke
runs against a live server; not part of automated phase gates.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


_TEST_ENV_DEFAULTS = {
    "ANTHROPIC_API_KEY": "test-anthropic-key",
    "PINECONE_API_KEY": "test-pinecone-key",
    "DEEN_DENSE_INDEX_NAME": "test-deen-dense",
    "DEEN_SPARSE_INDEX_NAME": "test-deen-sparse",
    "QURAN_DENSE_INDEX_NAME": "test-quran-dense",
    "DEEN_FIQH_DENSE_INDEX_NAME": "test-deen-fiqh-dense",
    "DEEN_FIQH_SPARSE_INDEX_NAME": "test-deen-fiqh-sparse",
    "REDIS_URL": "redis://127.0.0.1:1/0",
    "REDIS_KEY_PREFIX": "loadtest:chat",
    "ENV": "test",
    "DB_USER": "test-user",
    "DB_PASSWORD": "test-password",
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "5432",
    "DB_NAME": "test-db",
}
for _k, _v in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_k, _v)


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, int(round(len(s) * pct)) - 1)
    return s[idx]


async def _run_in_process(args) -> Dict[str, Any]:
    from tests.conftest_async_stubs import (  # noqa: E402  -- after env defaults
        StubConfig,
        install_pipeline_stubs,
        run_pipeline_concurrent,
    )

    cfg = StubConfig(
        llm_sleep_s=args.llm_sleep,
        retrieval_sleep_s=args.retrieval_sleep,
        per_token_sleep_s=args.per_token_sleep,
    )

    # One-call warmup so module imports / Anthropic class lookup happen outside
    # the timed window. Skip in --no-warmup runs.
    with install_pipeline_stubs(cfg):
        if not args.no_warmup:
            from tests.conftest_async_stubs import run_pipeline_once

            await run_pipeline_once()

        results = await run_pipeline_concurrent(n=args.n)

    expected_per_request_s = (
        cfg.llm_sleep_s * 2  # planner LLM iterations
        + cfg.retrieval_sleep_s  # one shia retrieval
        + cfg.per_token_sleep_s * len(cfg.tokens)  # streaming tokens
    )

    durations = results["per_request_s"]
    expected_serial_wall_s = expected_per_request_s * args.n

    return {
        "label": args.label,
        "mode": "in-process",
        "n": args.n,
        "stubs": {
            "llm_sleep_s": cfg.llm_sleep_s,
            "retrieval_sleep_s": cfg.retrieval_sleep_s,
            "per_token_sleep_s": cfg.per_token_sleep_s,
            "expected_per_request_s": round(expected_per_request_s, 4),
            "expected_serial_wall_s": round(expected_serial_wall_s, 4),
        },
        "wall_clock_s": round(results["wall_clock_s"], 4),
        "p50_s": round(results["p50_s"], 4),
        "p95_s": round(results["p95_s"], 4),
        "min_s": round(min(durations), 4),
        "max_s": round(max(durations), 4),
        "mean_s": round(statistics.mean(durations), 4),
        "throughput_rps": round(results["throughput_rps"], 4),
        "speedup_vs_serial": round(expected_serial_wall_s / results["wall_clock_s"], 4)
        if results["wall_clock_s"] > 0
        else None,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _emit_snapshot(snapshot_path: Path, payload: Dict[str, Any]) -> None:
    """Append a markdown row + JSON code block to documentation/async_baseline.md."""
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    if not snapshot_path.exists():
        header = (
            "# Async migration baseline (DEE-36)\n\n"
            "Per-phase concurrency snapshots produced by\n"
            "`python scripts/loadtest_agentic.py --emit-snapshot documentation/async_baseline.md`.\n\n"
            "Each entry below records wall-clock, p50/p95 per request, and the\n"
            "speedup vs. an idealised serial run with the same stubbed latencies.\n"
            "A speedup of 1.0 means full serialisation; the Phase 7 gate requires\n"
            "≥ 3.0 at N=10 vs. the Phase 0 entry.\n\n"
        )
        snapshot_path.write_text(header, encoding="utf-8")

    label = payload.get("label") or "(unlabeled)"
    section = (
        f"## {label} — {payload['timestamp']}\n\n"
        f"- mode: `{payload['mode']}`\n"
        f"- n: {payload['n']}\n"
        f"- wall_clock_s: **{payload['wall_clock_s']}**\n"
        f"- p50_s / p95_s: {payload['p50_s']} / {payload['p95_s']}\n"
        f"- throughput_rps: {payload['throughput_rps']}\n"
        f"- speedup_vs_serial: **{payload['speedup_vs_serial']}**\n\n"
        f"```json\n{json.dumps(payload, indent=2)}\n```\n\n"
    )
    with snapshot_path.open("a", encoding="utf-8") as fh:
        fh.write(section)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Agentic pipeline concurrency loadtest")
    parser.add_argument("--mode", choices=["in-process", "external"], default="in-process")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--n", type=int, default=10, help="Concurrent request count")
    parser.add_argument("--llm-sleep", type=float, default=0.2)
    parser.add_argument("--retrieval-sleep", type=float, default=0.1)
    parser.add_argument("--per-token-sleep", type=float, default=0.05)
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--label", default=None, help="Phase / commit label written into the snapshot")
    parser.add_argument("--emit-snapshot", default=None, help="Markdown file path to append the result")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.mode == "external":
        print(json.dumps({"error": "external mode is not implemented in DEE-39 (Phase 0)"}))
        return 2

    started = time.perf_counter()
    payload = asyncio.run(_run_in_process(args))
    payload["loadtest_runtime_s"] = round(time.perf_counter() - started, 4)

    print(json.dumps(payload, indent=2))

    if args.emit_snapshot:
        _emit_snapshot(Path(args.emit_snapshot), payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
