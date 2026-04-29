# Async migration baseline (DEE-36)

Per-phase concurrency snapshots produced by
`python scripts/loadtest_agentic.py --emit-snapshot documentation/async_baseline.md`.

Each entry below records wall-clock, p50/p95 per request, and the
speedup vs. an idealised serial run with the same stubbed latencies.
A speedup of 1.0 means full serialisation; the Phase 7 gate requires
≥ 3.0 at N=10 vs. the Phase 0 entry.

## phase-0 baseline (DEE-39) — 2026-04-29T19:14:15+00:00

- mode: `in-process`
- n: 10
- wall_clock_s: **3.4461**
- p50_s / p95_s: 2.3339 / 3.4441
- throughput_rps: 2.9019
- speedup_vs_serial: **2.1764**

```json
{
  "label": "phase-0 baseline (DEE-39)",
  "mode": "in-process",
  "n": 10,
  "stubs": {
    "llm_sleep_s": 0.2,
    "retrieval_sleep_s": 0.1,
    "per_token_sleep_s": 0.05,
    "expected_per_request_s": 0.75,
    "expected_serial_wall_s": 7.5
  },
  "wall_clock_s": 3.4461,
  "p50_s": 2.3339,
  "p95_s": 3.4441,
  "min_s": 0.969,
  "max_s": 3.4441,
  "mean_s": 2.2006,
  "throughput_rps": 2.9019,
  "speedup_vs_serial": 2.1764,
  "timestamp": "2026-04-29T19:14:15+00:00"
}
```

