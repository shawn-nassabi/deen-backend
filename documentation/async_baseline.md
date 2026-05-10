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

## phase-1 chain.astream (DEE-40) — 2026-04-29T19:22:59+00:00

- mode: `in-process`
- n: 10
- wall_clock_s: **0.9699**
- p50_s / p95_s: 0.9632 / 0.9686
- throughput_rps: 10.3107
- speedup_vs_serial: **7.733**

```json
{
  "label": "phase-1 chain.astream (DEE-40)",
  "mode": "in-process",
  "n": 10,
  "stubs": {
    "llm_sleep_s": 0.2,
    "retrieval_sleep_s": 0.1,
    "per_token_sleep_s": 0.05,
    "expected_per_request_s": 0.75,
    "expected_serial_wall_s": 7.5
  },
  "wall_clock_s": 0.9699,
  "p50_s": 0.9632,
  "p95_s": 0.9686,
  "min_s": 0.958,
  "max_s": 0.9686,
  "mean_s": 0.9629,
  "throughput_rps": 10.3107,
  "speedup_vs_serial": 7.733,
  "timestamp": "2026-04-29T19:22:59+00:00"
}
```

## phase-1 chain.astream (DEE-40) — 2026-04-29T19:31:10+00:00

- mode: `in-process`
- n: 10
- wall_clock_s: **0.9542**
- p50_s / p95_s: 0.9489 / 0.9536
- throughput_rps: 10.4802
- speedup_vs_serial: **7.8601**

```json
{
  "label": "phase-1 chain.astream (DEE-40)",
  "mode": "in-process",
  "n": 10,
  "stubs": {
    "llm_sleep_s": 0.2,
    "retrieval_sleep_s": 0.1,
    "per_token_sleep_s": 0.05,
    "expected_per_request_s": 0.75,
    "expected_serial_wall_s": 7.5
  },
  "wall_clock_s": 0.9542,
  "p50_s": 0.9489,
  "p95_s": 0.9536,
  "min_s": 0.8378,
  "max_s": 0.9536,
  "mean_s": 0.9269,
  "throughput_rps": 10.4802,
  "speedup_vs_serial": 7.8601,
  "timestamp": "2026-04-29T19:31:10+00:00"
}
```

## phase-2 async-nodes (DEE-41) — 2026-04-29T19:33:38+00:00

- mode: `in-process`
- n: 10
- wall_clock_s: **0.9451**
- p50_s / p95_s: 0.9386 / 0.9423
- throughput_rps: 10.5806
- speedup_vs_serial: **7.9354**

```json
{
  "label": "phase-2 async-nodes (DEE-41)",
  "mode": "in-process",
  "n": 10,
  "stubs": {
    "llm_sleep_s": 0.2,
    "retrieval_sleep_s": 0.1,
    "per_token_sleep_s": 0.05,
    "expected_per_request_s": 0.75,
    "expected_serial_wall_s": 7.5
  },
  "wall_clock_s": 0.9451,
  "p50_s": 0.9386,
  "p95_s": 0.9423,
  "min_s": 0.9311,
  "max_s": 0.9423,
  "mean_s": 0.9377,
  "throughput_rps": 10.5806,
  "speedup_vs_serial": 7.9354,
  "timestamp": "2026-04-29T19:33:38+00:00"
}
```

## phase-3 native-async-modules (DEE-42) — 2026-04-29T19:43:10+00:00

- mode: `in-process`
- n: 10
- wall_clock_s: **1.0039**
- p50_s / p95_s: 0.9959 / 1.0
- throughput_rps: 9.9612
- speedup_vs_serial: **7.4709**

```json
{
  "label": "phase-3 native-async-modules (DEE-42)",
  "mode": "in-process",
  "n": 10,
  "stubs": {
    "llm_sleep_s": 0.2,
    "retrieval_sleep_s": 0.1,
    "per_token_sleep_s": 0.05,
    "expected_per_request_s": 0.75,
    "expected_serial_wall_s": 7.5
  },
  "wall_clock_s": 1.0039,
  "p50_s": 0.9959,
  "p95_s": 1.0,
  "min_s": 0.8466,
  "max_s": 1.0,
  "mean_s": 0.9809,
  "throughput_rps": 9.9612,
  "speedup_vs_serial": 7.4709,
  "timestamp": "2026-04-29T19:43:10+00:00"
}
```

## phase-4 async-redis (DEE-43) — 2026-04-29T20:06:52+00:00

- mode: `in-process`
- n: 10
- wall_clock_s: **0.9675**
- p50_s / p95_s: 0.961 / 0.9663
- throughput_rps: 10.3363
- speedup_vs_serial: **7.7522**

```json
{
  "label": "phase-4 async-redis (DEE-43)",
  "mode": "in-process",
  "n": 10,
  "stubs": {
    "llm_sleep_s": 0.2,
    "retrieval_sleep_s": 0.1,
    "per_token_sleep_s": 0.05,
    "expected_per_request_s": 0.75,
    "expected_serial_wall_s": 7.5
  },
  "wall_clock_s": 0.9675,
  "p50_s": 0.961,
  "p95_s": 0.9663,
  "min_s": 0.843,
  "max_s": 0.9663,
  "mean_s": 0.9493,
  "throughput_rps": 10.3363,
  "speedup_vs_serial": 7.7522,
  "timestamp": "2026-04-29T20:06:52+00:00"
}
```

## phase-4 async-redis (DEE-43) — 2026-04-29T20:12:27+00:00

- mode: `in-process`
- n: 10
- wall_clock_s: **0.6116**
- p50_s / p95_s: 0.5912 / 0.5933
- throughput_rps: 16.35
- speedup_vs_serial: **12.2625**

```json
{
  "label": "phase-4 async-redis (DEE-43)",
  "mode": "in-process",
  "n": 10,
  "stubs": {
    "llm_sleep_s": 0.2,
    "retrieval_sleep_s": 0.1,
    "per_token_sleep_s": 0.05,
    "expected_per_request_s": 0.75,
    "expected_serial_wall_s": 7.5
  },
  "wall_clock_s": 0.6116,
  "p50_s": 0.5912,
  "p95_s": 0.5933,
  "min_s": 0.5866,
  "max_s": 0.5933,
  "mean_s": 0.5907,
  "throughput_rps": 16.35,
  "speedup_vs_serial": 12.2625,
  "timestamp": "2026-04-29T20:12:27+00:00"
}
```

## phase-5 async-fiqh-and-routes (DEE-44) — 2026-04-29T20:26:38+00:00

- mode: `in-process`
- n: 10
- wall_clock_s: **0.5711**
- p50_s / p95_s: 0.5608 / 0.562
- throughput_rps: 17.5116
- speedup_vs_serial: **13.1337**

```json
{
  "label": "phase-5 async-fiqh-and-routes (DEE-44)",
  "mode": "in-process",
  "n": 10,
  "stubs": {
    "llm_sleep_s": 0.2,
    "retrieval_sleep_s": 0.1,
    "per_token_sleep_s": 0.05,
    "expected_per_request_s": 0.75,
    "expected_serial_wall_s": 7.5
  },
  "wall_clock_s": 0.5711,
  "p50_s": 0.5608,
  "p95_s": 0.562,
  "min_s": 0.5567,
  "max_s": 0.562,
  "mean_s": 0.5593,
  "throughput_rps": 17.5116,
  "speedup_vs_serial": 13.1337,
  "timestamp": "2026-04-29T20:26:38+00:00"
}
```

## phase-5 async-fiqh-and-routes (DEE-44) — 2026-05-09T05:28:10+00:00

- mode: `in-process`
- n: 10
- wall_clock_s: **0.929**
- p50_s / p95_s: 0.9172 / 0.9282
- throughput_rps: 10.7645
- speedup_vs_serial: **8.0733**

```json
{
  "label": "phase-5 async-fiqh-and-routes (DEE-44)",
  "mode": "in-process",
  "n": 10,
  "stubs": {
    "llm_sleep_s": 0.2,
    "retrieval_sleep_s": 0.1,
    "per_token_sleep_s": 0.05,
    "expected_per_request_s": 0.75,
    "expected_serial_wall_s": 7.5
  },
  "wall_clock_s": 0.929,
  "p50_s": 0.9172,
  "p95_s": 0.9282,
  "min_s": 0.9025,
  "max_s": 0.9282,
  "mean_s": 0.9156,
  "throughput_rps": 10.7645,
  "speedup_vs_serial": 8.0733,
  "timestamp": "2026-05-09T05:28:10+00:00"
}
```

## phase-7 verification (DEE-46) — 2026-05-09T05:30:56+00:00

- mode: `in-process`
- n: 10
- wall_clock_s: **0.9369**
- p50_s / p95_s: 0.9227 / 0.9363
- throughput_rps: 10.6732
- speedup_vs_serial: **8.0049**

```json
{
  "label": "phase-7 verification (DEE-46)",
  "mode": "in-process",
  "n": 10,
  "stubs": {
    "llm_sleep_s": 0.2,
    "retrieval_sleep_s": 0.1,
    "per_token_sleep_s": 0.05,
    "expected_per_request_s": 0.75,
    "expected_serial_wall_s": 7.5
  },
  "wall_clock_s": 0.9369,
  "p50_s": 0.9227,
  "p95_s": 0.9363,
  "min_s": 0.9063,
  "max_s": 0.9363,
  "mean_s": 0.9209,
  "throughput_rps": 10.6732,
  "speedup_vs_serial": 8.0049,
  "timestamp": "2026-05-09T05:30:56+00:00",
  "loadtest_runtime_s": 15.4907
}
```

## phase-5 async-fiqh-and-routes (DEE-44) — 2026-05-09T05:36:22+00:00

- mode: `in-process`
- n: 10
- wall_clock_s: **0.9413**
- p50_s / p95_s: 0.9269 / 0.9405
- throughput_rps: 10.6236
- speedup_vs_serial: **7.9677**

```json
{
  "label": "phase-5 async-fiqh-and-routes (DEE-44)",
  "mode": "in-process",
  "n": 10,
  "stubs": {
    "llm_sleep_s": 0.2,
    "retrieval_sleep_s": 0.1,
    "per_token_sleep_s": 0.05,
    "expected_per_request_s": 0.75,
    "expected_serial_wall_s": 7.5
  },
  "wall_clock_s": 0.9413,
  "p50_s": 0.9269,
  "p95_s": 0.9405,
  "min_s": 0.9129,
  "max_s": 0.9405,
  "mean_s": 0.9259,
  "throughput_rps": 10.6236,
  "speedup_vs_serial": 7.9677,
  "timestamp": "2026-05-09T05:36:22+00:00"
}
```

## phase-5 async-fiqh-and-routes (DEE-44) — 2026-05-10T02:23:32+00:00

- mode: `in-process`
- n: 10
- wall_clock_s: **0.9658**
- p50_s / p95_s: 0.9522 / 0.965
- throughput_rps: 10.3543
- speedup_vs_serial: **7.7657**

```json
{
  "label": "phase-5 async-fiqh-and-routes (DEE-44)",
  "mode": "in-process",
  "n": 10,
  "stubs": {
    "llm_sleep_s": 0.2,
    "retrieval_sleep_s": 0.1,
    "per_token_sleep_s": 0.05,
    "expected_per_request_s": 0.75,
    "expected_serial_wall_s": 7.5
  },
  "wall_clock_s": 0.9658,
  "p50_s": 0.9522,
  "p95_s": 0.965,
  "min_s": 0.9423,
  "max_s": 0.965,
  "mean_s": 0.9519,
  "throughput_rps": 10.3543,
  "speedup_vs_serial": 7.7657,
  "timestamp": "2026-05-10T02:23:32+00:00"
}
```

## phase-5 async-fiqh-and-routes (DEE-44) — 2026-05-10T21:43:29+00:00

- mode: `in-process`
- n: 10
- wall_clock_s: **0.8253**
- p50_s / p95_s: 0.8184 / 0.8248
- throughput_rps: 12.1164
- speedup_vs_serial: **9.0873**

```json
{
  "label": "phase-5 async-fiqh-and-routes (DEE-44)",
  "mode": "in-process",
  "n": 10,
  "stubs": {
    "llm_sleep_s": 0.2,
    "retrieval_sleep_s": 0.1,
    "per_token_sleep_s": 0.05,
    "expected_per_request_s": 0.75,
    "expected_serial_wall_s": 7.5
  },
  "wall_clock_s": 0.8253,
  "p50_s": 0.8184,
  "p95_s": 0.8248,
  "min_s": 0.8106,
  "max_s": 0.8248,
  "mean_s": 0.8174,
  "throughput_rps": 12.1164,
  "speedup_vs_serial": 9.0873,
  "timestamp": "2026-05-10T21:43:29+00:00"
}
```

