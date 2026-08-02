"""
Token-usage bench for the agentic pipeline (token-cost initiative, Phase 0).

Drives a LIVE local server (real Anthropic + Pinecone + Redis/Postgres via the
dev .env) over the golden query set in tests/golden_queries.py, and records a
per-call-site token/cost breakdown per request from the debug `usage` SSE
event emitted by core/pipeline_langgraph.py.

The fiqh and general pipelines are different code paths, so results are
aggregated and reported as separate slices (general / fiqh / routing).

Run:
    # 1. Start the server WITH the debug usage event enabled:
    #    PowerShell:  $env:TOKEN_BENCH_DEBUG="1"; uvicorn main:app --port 8000
    #    bash:        TOKEN_BENCH_DEBUG=1 uvicorn main:app --port 8000
    # 2. Run the bench (defaults: all 32 entries, sequential):
    python scripts/token_bench.py --label phase-0-baseline
    python scripts/token_bench.py --label phase-0-fiqh --slice fiqh
    python scripts/token_bench.py --ids gen-patience,fiqh-shrimp --no-snapshot

    # A/B LLM-judge between two recorded runs (same golden ids, blind pairs):
    python scripts/token_bench.py --judge phase-0-baseline phase-1-candidate

Snapshots append to documentation/token_baseline.md (markdown section + JSON
code block, mirroring scripts/loadtest_agentic.py -> documentation/async_baseline.md
so a future ratchet test can regex-parse them).

Cost model (list prices, USD per MTok): claude-sonnet-4-6 $3 in / $15 out,
claude-haiku-4-5 $1 in / $5 out; cache read 0.1x input, cache write 1.25x
(5-minute TTL). The enhancer is the only Haiku site today.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:  # Windows consoles default to cp1252; golden set contains Urdu/Arabic.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

DEFAULT_URL = "http://127.0.0.1:8000"
DEFAULT_SNAPSHOT = "documentation/token_baseline.md"
REQUEST_TIMEOUT_S = 240.0

USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)

# Site -> model family for pricing. Everything is Sonnet except the enhancer
# (the sole SMALL_LLM consumer today). Keep in sync with core/chat_models.py.
HAIKU_SITES = {"enhancer"}
PRICES_PER_MTOK = {"sonnet": (3.0, 15.0), "haiku": (1.0, 5.0)}
CACHE_READ_MULT = 0.1
CACHE_WRITE_MULT = 1.25

RETRIEVAL_STEPS = {
    "retrieve_shia_documents_tool",
    "retrieve_sunni_documents_tool",
    "retrieve_quran_tafsir_tool",
}
FIQH_STEPS_PREFIX = "fiqh_"

ANSWER_SNAPSHOT_CAP = 6000  # chars stored per answer (judge input)


# ---------------------------------------------------------------------------
# SSE client
# ---------------------------------------------------------------------------


def _parse_sse(raw: str) -> List[Tuple[str, Any]]:
    """Parse an SSE body into (event_type, data) tuples."""
    events: List[Tuple[str, Any]] = []
    for block in raw.split("\n\n"):
        event_type = None
        data_lines: List[str] = []
        for line in block.splitlines():
            if line.startswith("event: "):
                event_type = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data_lines.append(line[len("data: "):])
        if event_type is None:
            continue
        data_raw = "\n".join(data_lines)
        try:
            data = json.loads(data_raw) if data_raw else {}
        except json.JSONDecodeError:
            data = {"_raw": data_raw}
        events.append((event_type, data))
    return events


async def _drive_turn(client, url: str, query: str, session_id: str, language: str) -> Dict[str, Any]:
    body = {"user_query": query, "session_id": session_id, "language": language}
    started = time.perf_counter()
    chunks: List[str] = []
    async with client.stream("POST", f"{url}/chat/stream/agentic", json=body) as resp:
        resp.raise_for_status()
        async for chunk in resp.aiter_text():
            chunks.append(chunk)
    elapsed = time.perf_counter() - started

    events = _parse_sse("".join(chunks))
    answer_parts: List[str] = []
    status_steps: List[str] = []
    usage: Optional[Dict[str, Any]] = None
    refs = {"hadith_references": 0, "quran_references": 0, "fiqh_references": 0}
    errors: List[str] = []

    for event_type, data in events:
        if event_type == "response_chunk":
            answer_parts.append(str(data.get("token", "")))
        elif event_type == "status":
            step = data.get("step")
            if step:
                status_steps.append(step)
        elif event_type == "usage":
            usage = data
        elif event_type in refs:
            payload = data.get("references", data)
            refs[event_type] = len(payload) if isinstance(payload, list) else 1
        elif event_type == "error":
            errors.append(str(data.get("message", "")))

    answer = "".join(answer_parts)
    return {
        "query": query if len(query) <= 200 else query[:200] + "…",
        "elapsed_s": round(elapsed, 2),
        "event_types": [t for t, _ in events],
        "status_steps": status_steps,
        "usage_by_site": (usage or {}).get("by_site", {}),
        "usage_totals": (usage or {}).get("totals", {}),
        "usage_present": usage is not None,
        "answer_chars": len(answer),
        "answer": answer[:ANSWER_SNAPSHOT_CAP],
        "references": refs,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Routing / quality checks (deterministic)
# ---------------------------------------------------------------------------


def _observed_route(turn: Dict[str, Any]) -> str:
    steps = turn["status_steps"]
    if any(s.startswith(FIQH_STEPS_PREFIX) or s == "generate_fiqh_response" for s in steps):
        return "fiqh"
    if any(s in RETRIEVAL_STEPS for s in steps) or "generate_response" in steps:
        return "agent"
    return "early_exit"


def _check_entry(entry: Dict[str, Any], turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    expect = entry["expect"]
    last = turns[-1]
    observed = _observed_route(last)
    if expect in ("early_exit", "casual"):
        routing_ok = observed == "early_exit"
    else:
        routing_ok = observed == expect

    checks: Dict[str, Any] = {"observed_route": observed, "routing_ok": routing_ok}
    if expect == "fiqh":
        checks["has_fiqh_disclaimer"] = "Ayatollah Sistani's published rulings" in last["answer"]
        checks["has_sources_or_refs"] = (
            "## Sources" in last["answer"] or last["references"]["fiqh_references"] > 0
        )
    elif expect == "agent":
        checks["has_references"] = (
            last["references"]["hadith_references"] > 0
            or last["references"]["quran_references"] > 0
        )
    elif expect in ("early_exit", "casual"):
        checks["no_retrieval"] = not any(
            s in RETRIEVAL_STEPS for t in turns for s in t["status_steps"]
        )
    return checks


# ---------------------------------------------------------------------------
# Aggregation + cost
# ---------------------------------------------------------------------------


def _site_cost_usd(site: str, rec: Dict[str, int]) -> float:
    family = "haiku" if site in HAIKU_SITES else "sonnet"
    p_in, p_out = PRICES_PER_MTOK[family]
    return (
        rec.get("input_tokens", 0) * p_in
        + rec.get("cache_read_input_tokens", 0) * p_in * CACHE_READ_MULT
        + rec.get("cache_creation_input_tokens", 0) * p_in * CACHE_WRITE_MULT
        + rec.get("output_tokens", 0) * p_out
    ) / 1_000_000


def _merge_by_site(target: Dict[str, Dict[str, int]], source: Dict[str, Dict[str, int]]) -> None:
    for site, rec in (source or {}).items():
        slot = target.setdefault(site, {"calls": 0, **{k: 0 for k in USAGE_FIELDS}})
        slot["calls"] += int(rec.get("calls", 0) or 0)
        for k in USAGE_FIELDS:
            slot[k] += int(rec.get(k, 0) or 0)


def _aggregate(entry_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_site: Dict[str, Dict[str, int]] = {}
    n_turns = 0
    for entry in entry_results:
        for turn in entry["turns"]:
            n_turns += 1
            _merge_by_site(by_site, turn["usage_by_site"])
    totals = {"calls": 0, **{k: 0 for k in USAGE_FIELDS}}
    cost = 0.0
    for site, rec in by_site.items():
        totals["calls"] += rec["calls"]
        for k in USAGE_FIELDS:
            totals[k] += rec[k]
        cost += _site_cost_usd(site, rec)
    return {
        "entries": len(entry_results),
        "turns": n_turns,
        "by_site": by_site,
        "totals": totals,
        "cost_usd": round(cost, 4),
        "mean_cost_per_turn_usd": round(cost / n_turns, 4) if n_turns else 0.0,
        "mean_input_tokens_per_turn": round(totals["input_tokens"] / n_turns, 1) if n_turns else 0.0,
    }


def _usage_table_md(by_site: Dict[str, Dict[str, int]]) -> str:
    lines = [
        "| site | calls | input | output | cache_read | cache_write | $ |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for site in sorted(by_site):
        rec = by_site[site]
        lines.append(
            f"| {site} | {rec['calls']} | {rec['input_tokens']:,} | {rec['output_tokens']:,} "
            f"| {rec['cache_read_input_tokens']:,} | {rec['cache_creation_input_tokens']:,} "
            f"| {_site_cost_usd(site, rec):.4f} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bench runner
# ---------------------------------------------------------------------------


async def run_bench(args) -> Dict[str, Any]:
    import httpx

    from tests.golden_queries import entries

    selected = entries(slice_filter=args.slice, ids=args.ids.split(",") if args.ids else None)
    if args.limit:
        selected = selected[: args.limit]
    if not selected:
        raise SystemExit("No golden entries matched the filter.")

    run_ts = datetime.now(timezone.utc).strftime("%y%m%d%H%M%S")
    results: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT_S)) as client:
        for i, entry in enumerate(selected, 1):
            session_id = f"tb-{run_ts}-{entry['id']}"
            turns: List[Dict[str, Any]] = []
            for turn_query in entry["turns"]:
                print(f"[{i}/{len(selected)}] {entry['id']}: {turn_query[:70]}", flush=True)
                turn = await _drive_turn(
                    client, args.url, turn_query, session_id, entry["language"]
                )
                turns.append(turn)
                if not turn["usage_present"]:
                    raise SystemExit(
                        "No `usage` SSE event received. Start the server with "
                        "TOKEN_BENCH_DEBUG=1 (PowerShell: $env:TOKEN_BENCH_DEBUG=\"1\"; "
                        "uvicorn main:app --port 8000) and re-run."
                    )
            checks = _check_entry(entry, turns)
            results.append(
                {
                    "id": entry["id"],
                    "slice": entry["slice"],
                    "expect": entry["expect"],
                    **checks,
                    "turns": turns,
                }
            )

    slices: Dict[str, Any] = {}
    for slice_name in ("general", "fiqh", "routing"):
        slice_entries = [r for r in results if r["slice"] == slice_name]
        if slice_entries:
            slices[slice_name] = _aggregate(slice_entries)

    overall = _aggregate(results)
    routing_failures = [r["id"] for r in results if not r["routing_ok"]]

    return {
        "label": args.label,
        "mode": "token-bench",
        "url": args.url,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_entries": len(results),
        "overall": overall,
        "slices": slices,
        "routing_failures": routing_failures,
        "entries": results,
    }


def _print_report(payload: Dict[str, Any]) -> None:
    print("\n" + "=" * 72)
    print(f"Token bench — label={payload['label']!r} — {payload['timestamp']}")
    print("=" * 72)
    for slice_name, agg in payload["slices"].items():
        print(
            f"\n--- slice: {slice_name} "
            f"({agg['entries']} entries / {agg['turns']} turns, "
            f"${agg['cost_usd']} total, ${agg['mean_cost_per_turn_usd']}/turn, "
            f"{agg['mean_input_tokens_per_turn']} uncached input tok/turn) ---"
        )
        print(_usage_table_md(agg["by_site"]))
    overall = payload["overall"]
    print(
        f"\nOVERALL: {overall['turns']} turns | "
        f"input {overall['totals']['input_tokens']:,} | "
        f"output {overall['totals']['output_tokens']:,} | "
        f"cache_read {overall['totals']['cache_read_input_tokens']:,} | "
        f"cache_write {overall['totals']['cache_creation_input_tokens']:,} | "
        f"${overall['cost_usd']}"
    )
    if payload["routing_failures"]:
        print(f"\nROUTING CHECK FAILURES: {payload['routing_failures']}")
    else:
        print("\nAll routing checks passed.")


def _emit_snapshot(snapshot_path: Path, payload: Dict[str, Any]) -> None:
    """Append a markdown section + JSON code block (loadtest_agentic pattern)."""
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    if not snapshot_path.exists():
        header = (
            "# Token-usage baseline (token-cost initiative)\n\n"
            "Per-phase token/cost snapshots produced by\n"
            "`python scripts/token_bench.py --label <phase> --emit-snapshot documentation/token_baseline.md`.\n\n"
            "Each entry records per-call-site raw Anthropic usage (uncached input /\n"
            "output / cache read / cache write) per golden-set slice, plus list-price\n"
            "cost. The fiqh and general pipelines are separate slices. Phase gates\n"
            "compare a candidate label against the phase-0 baseline label.\n\n"
            "See `documentation/token_cost_reduction_plan.md` for the phase plan.\n\n"
        )
        snapshot_path.write_text(header, encoding="utf-8")

    label = payload.get("label") or "(unlabeled)"
    overall = payload["overall"]
    slice_bits = []
    for slice_name, agg in payload["slices"].items():
        slice_bits.append(
            f"- {slice_name}: {agg['turns']} turns, "
            f"{agg['totals']['input_tokens']:,} in / {agg['totals']['output_tokens']:,} out / "
            f"{agg['totals']['cache_read_input_tokens']:,} cache-read / "
            f"{agg['totals']['cache_creation_input_tokens']:,} cache-write, "
            f"${agg['cost_usd']}"
        )
    section = (
        f"## {label} — {payload['timestamp']}\n\n"
        f"- n_entries: {payload['n_entries']}\n"
        + "\n".join(slice_bits)
        + f"\n- overall cost: **${overall['cost_usd']}** "
        f"(${overall['mean_cost_per_turn_usd']}/turn)\n"
        f"- routing failures: {payload['routing_failures'] or 'none'}\n\n"
        f"```json\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n```\n\n"
    )
    with snapshot_path.open("a", encoding="utf-8") as fh:
        fh.write(section)


# ---------------------------------------------------------------------------
# A/B LLM judge over two recorded runs
# ---------------------------------------------------------------------------

JUDGE_RUBRIC = """You are grading two answers (A and B) from an Islamic education \
assistant that must answer from the Twelver Shia perspective, grounded in retrieved \
hadith/Quran/fiqh references, never fabricating citations.

User question:
{question}

Answer A:
{answer_a}

Answer B:
{answer_b}

Score EACH answer 1-5 on: groundedness (claims backed by cited sources; no invented \
citations), citation_completeness (citations carry book/chapter/number detail), \
shia_fidelity (accurate Twelver Shia framing), usefulness (clear, addresses the \
question). Then pick the overall better answer ("A", "B", or "tie").

Respond with STRICT JSON only:
{{"a": {{"groundedness": n, "citation_completeness": n, "shia_fidelity": n, "usefulness": n}},
  "b": {{"groundedness": n, "citation_completeness": n, "shia_fidelity": n, "usefulness": n}},
  "winner": "A|B|tie", "reason": "<one sentence>"}}"""


def _parse_snapshots(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"Snapshot file not found: {path}")
    text = path.read_text(encoding="utf-8")
    payloads = []
    for match in re.finditer(r"```json\n(.*?)\n```", text, flags=re.DOTALL):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if payload.get("mode") == "token-bench":
            payloads.append(payload)
    return payloads


def _latest_run(payloads: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    runs = [p for p in payloads if p.get("label") == label]
    if not runs:
        raise SystemExit(f"No token-bench run with label {label!r} in the snapshot file.")
    return runs[-1]


def run_judge(args) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    import os

    import anthropic

    baseline_label, candidate_label = args.judge
    payloads = _parse_snapshots(Path(args.emit_snapshot))
    baseline = _latest_run(payloads, baseline_label)
    candidate = _latest_run(payloads, candidate_label)

    base_answers = {
        e["id"]: e["turns"][-1]["answer"]
        for e in baseline["entries"]
        if e["turns"][-1].get("answer")
    }
    cand_answers = {
        e["id"]: e["turns"][-1]["answer"]
        for e in candidate["entries"]
        if e["turns"][-1].get("answer")
    }
    questions = {e["id"]: e["turns"][-1]["query"] for e in candidate["entries"]}
    shared = sorted(
        i for i in base_answers.keys() & cand_answers.keys()
        if not i.startswith("route-")  # refusal/casual texts aren't judge-worthy
    )
    if not shared:
        raise SystemExit("No shared answered entries between the two runs.")

    client = anthropic.Anthropic()
    judge_model = os.getenv("LARGE_LLM", "claude-sonnet-4-6")
    wins = {"baseline": 0, "candidate": 0, "tie": 0}
    axis_sums = {"baseline": {}, "candidate": {}}
    verdicts = []

    for entry_id in shared:
        # Blind, per-entry-deterministic position shuffle.
        flipped = random.Random(entry_id).random() < 0.5
        a_text = cand_answers[entry_id] if flipped else base_answers[entry_id]
        b_text = base_answers[entry_id] if flipped else cand_answers[entry_id]
        prompt = JUDGE_RUBRIC.format(
            question=questions.get(entry_id, entry_id), answer_a=a_text, answer_b=b_text
        )
        response = client.messages.create(
            model=judge_model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        try:
            verdict = json.loads(re.search(r"\{.*\}", raw, flags=re.DOTALL).group(0))
        except Exception:  # noqa: BLE001
            print(f"  [judge] unparseable verdict for {entry_id}: {raw[:200]}")
            continue

        key_a, key_b = ("candidate", "baseline") if flipped else ("baseline", "candidate")
        for role, side in ((key_a, "a"), (key_b, "b")):
            for axis, score in (verdict.get(side) or {}).items():
                axis_sums[role][axis] = axis_sums[role].get(axis, 0) + float(score)
        winner = str(verdict.get("winner", "tie")).strip().upper()
        if winner == "A":
            wins[key_a] += 1
        elif winner == "B":
            wins[key_b] += 1
        else:
            wins["tie"] += 1
        verdicts.append({"id": entry_id, "winner_role": key_a if winner == "A" else key_b if winner == "B" else "tie", "reason": verdict.get("reason", "")})
        print(f"  [judge] {entry_id}: {verdicts[-1]['winner_role']}")

    n = len(verdicts)
    print("\n" + "=" * 72)
    print(f"Judge A/B — baseline={baseline_label!r} vs candidate={candidate_label!r} ({n} pairs)")
    print("=" * 72)
    print(f"wins: baseline={wins['baseline']} candidate={wins['candidate']} tie={wins['tie']}")
    for role in ("baseline", "candidate"):
        means = {axis: round(total / n, 2) for axis, total in axis_sums[role].items()} if n else {}
        print(f"{role} mean scores: {means}")
    print("\nGate guidance: candidate must not lose on groundedness or "
          "citation_completeness means, and win+tie must be >= 80% of pairs.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Agentic pipeline token-usage bench")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--label", default=None, help="Phase label written into the snapshot")
    parser.add_argument("--slice", choices=["all", "general", "fiqh", "routing"], default="all")
    parser.add_argument("--ids", default=None, help="Comma-separated golden entry ids")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--emit-snapshot", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--no-snapshot", action="store_true")
    parser.add_argument(
        "--judge",
        nargs=2,
        metavar=("BASELINE_LABEL", "CANDIDATE_LABEL"),
        default=None,
        help="Skip the bench; LLM-judge two recorded runs from the snapshot file",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.judge:
        return run_judge(args)

    started = time.perf_counter()
    payload = asyncio.run(run_bench(args))
    payload["bench_runtime_s"] = round(time.perf_counter() - started, 1)

    _print_report(payload)
    if not args.no_snapshot:
        _emit_snapshot(Path(args.emit_snapshot), payload)
        print(f"\nSnapshot appended to {args.emit_snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
