# Phase 19: Observability and Verification - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-03
**Phase:** 19-observability-and-verification
**Areas discussed:** Session boundary, Coverage of call sites, Multi-iteration aggregation, DEE-50 update plan

---

## Session boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Per HTTP turn | One breadcrumb per /chat/stream/agentic request, fired at end of SSE stream before the final `done` event. Maps cleanly to existing correlation_id boundary. No Redis/DB aggregation. | ✓ |
| Per Redis session_id (multi-turn) | One breadcrumb per durable session_id covering all turns until TTL or session close. Requires new persistence surface (Redis hash or DB table) for per-turn metrics. | |
| Both | Per-turn breadcrumb plus rolling per-session aggregate. Doubles implementation cost and Sentry noise. | |

**User's choice:** Per HTTP turn (Recommended)
**Notes:** Matches Sentry per-request scope model and the existing event boundaries in `core/pipeline_langgraph.py`. No new persistence surface needed.

---

## Coverage of call sites

| Option | Description | Selected |
|--------|-------------|----------|
| _agent_node only | Aggregate only the cache_creation/cache_read tokens already logged at agents/core/chat_agent.py:184-199. Honest signal — only call site where caching reliably hits today. | ✓ |
| _agent_node + _generate_response_node | Add cache-metrics logging to _generate_response_node and roll its tokens in. Generator prompt below threshold today — contributes zeros, dilutes ratio. | |
| All cached call sites (agent + generator + fiqh sub-graph) | Also instrument the 6 fiqh sub-graph LLM calls. Most below threshold; contributions all-zero, masks real ChatAgent cache signal. | |

**User's choice:** _agent_node only (Recommended)
**Notes:** Phase 17 D-05 already deferred `_generate_response_node` metrics; Phase 19 holds that line. Fiqh and other modules excluded for the same reason — their inclusion would distort the ratio with deterministic zeros.

---

## Multi-iteration aggregation

| Option | Description | Selected |
|--------|-------------|----------|
| Sum tokens, then divide | Accumulate cache_read and cache_creation tokens across all _agent_node calls in the turn, then ratio = sum_read / (sum_read + sum_creation). Token-weighted measure that matches Anthropic billing. | ✓ |
| First call only | Use only iteration 1's metrics. After cold start, always 0%; on warm second turn, pure cache-hit signal. Easier to reason about but discards real data. | |
| Mean of per-call ratios | Compute ratio per call, then average. Treats each iteration equally regardless of token count — misleading. | |

**User's choice:** Sum tokens, then divide (Recommended)
**Notes:** Cold-cache edge case (denominator = 0) defined as `cache_efficiency_ratio = 0.0` per ROADMAP.md success criterion 2. Implementation must explicitly guard against ZeroDivisionError.

---

## DEE-50 update plan (split into two questions)

### Measurement threshold

| Option | Description | Selected |
|--------|-------------|----------|
| Single warm-cache turn | After deploy, one /chat/stream/agentic request that hits the warm prefix is enough — capture breadcrumb screenshot and ratio value. | ✓ |
| N sessions over 24 hours | Wait 24h, pull cache_efficiency_ratio distribution from ≥10 sessions. Captures cold + warm in realistic mixed traffic. | |
| Multi-day baseline + rerun | Baseline over 3+ days, summarize distribution, re-run after next deployment. Most rigorous but extends phase indefinitely. | |

**User's choice:** Single warm-cache turn
**Notes:** Matches the Phase 17 two-call manual verification pattern. Multi-day baseline deferred as post-phase observation work, not implementation work.

### Update artifact

| Option | Description | Selected |
|--------|-------------|----------|
| Linear comment with measurement | Single comment on DEE-50 with eligible call sites, approach taken, and measured ratio numbers. Comment preserves chronological 'before vs after deploy' context. | ✓ |
| Linear description edit | Edit the main ticket description to embed details + measurements. Cleaner top-of-ticket but loses chronological history. | |
| Both: doc in repo + Linear pointer | Markdown doc in repo (e.g., docs/llm-caching.md) linked from DEE-50. More durable but more files to maintain. | |

**User's choice:** Linear comment with measurement (Recommended)
**Notes:** Comment will cite Phase 17 and Phase 18 CONTEXT.md "Primary Change Files" sections directly for the eligible call sites — no need to re-derive. The DEE-50 update is a manual post-deploy step; the phase plan must mark OBS-02 as a post-deploy checklist item, not an executable task that blocks verification.

---

## Claude's Discretion

- Exact ContextVar name vs ChatState field names for the per-turn accumulator (D-07) — both options are viable; planner picks based on which is least invasive given the SSE generator's existing `final_state.get(...)` reads
- Exact breadcrumb `category` and `message` strings (D-08) — follow existing Sentry conventions
- Whether the breadcrumb helper lives in `core/sentry.py` (alongside `bind_sentry_scope`) or a new module — `core/sentry.py` is the natural home
- Whether tests cover breadcrumb emission via Sentry SDK mocking, or only assert the in-memory accumulator math — both work; mocking Sentry is heavier than a unit-level seam on the helper

## Deferred Ideas

- Per-Redis-session multi-turn aggregation (rolling cache metrics across all turns within a session_id)
- `_generate_response_node` cache-metrics logging (revisit if/when prompt grows past 2048-token threshold)
- Fiqh sub-graph cache-metrics logging (revisit when prompts grow or model swap moves them above threshold)
- Multi-day production baseline + post-redeploy comparison
- Sentry dashboard / alerting rules on `cache_efficiency_ratio`
- Cache cost dashboard / billing reconciliation against Anthropic billing API
