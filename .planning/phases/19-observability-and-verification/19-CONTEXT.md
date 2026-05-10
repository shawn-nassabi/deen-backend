# Phase 19: Observability and Verification - Context

**Gathered:** 2026-05-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Make Anthropic prompt-cache efficiency visible per chat turn as a Sentry breadcrumb (OBS-01), and update Linear ticket DEE-50 with implementation details and a measured cache hit rate from production (OBS-02). The ChatAgent already logs raw cache_creation/cache_read tokens at DEBUG inside `_agent_node` (Phase 17 D-05) — Phase 19 wires those numbers into a per-turn aggregate and a Sentry breadcrumb fired at the SSE stream's `done` boundary. No new persistence surfaces (no Redis/DB additions). No new instrumentation on `_generate_response_node` or fiqh sub-graph LLM calls — those remain DEBUG-only or unlogged. Out of scope: cross-turn (multi-request) session aggregation, dashboards, alerting rules, multi-day production baselines.

</domain>

<decisions>
## Implementation Decisions

### Session boundary
- **D-01:** "A completed chat session" for the OBS-01 breadcrumb means **one HTTP turn** — i.e., one `/chat/stream/agentic` (or `/chat/agentic`) request. One breadcrumb per request. The Redis-backed multi-turn session_id is NOT the aggregation unit; we're not introducing per-session rolling state in Redis or DB for this phase. Per-turn matches the existing correlation_id boundary, the SSE `done` event, and Sentry's per-request isolation scope.
- **D-02:** The breadcrumb is fired **at the SSE generator's terminal `done` boundary** in `core/pipeline_langgraph.py`. There are five `done` emission sites (lines 201, 219, 378, plus error paths); the breadcrumb must fire on every successful path. Fire location must be inside the same scope/ContextVar lifetime as the request — i.e., before the SSE generator returns control to FastAPI.

### Coverage of cache metrics
- **D-03:** Only `_agent_node` cache metrics contribute to the per-turn breadcrumb ratio. This is the only call site where caching reliably hits today (tools+system prefix clears the 2048-token Sonnet threshold) and the only site already logging metrics. `_generate_response_node` is excluded (no metrics today, prompt below threshold — Phase 17 D-05 deferred). Fiqh sub-graph LLM calls (decomposer/classifier/refiner/sea/generator/filter — all instrumented in Phase 18 with `make_cached_system_message`) are excluded — most are below the Haiku 4096 / Sonnet 2048 threshold; including them would dilute the ratio with deterministic zeros and obscure the real ChatAgent cache signal.
- **D-04:** Source of metrics is the same as Phase 17: `response.response_metadata["usage"]` raw Anthropic dict, NEVER `response.usage_metadata` (LangChain double-counting bug, GitHub #32818). The numbers are already extracted at `agents/core/chat_agent.py:188-190` (`_cache_creation`, `_cache_read`) — Phase 19 reuses them, does not re-source them.

### Multi-iteration aggregation
- **D-05:** `_agent_node` may run N times per turn (LangGraph tool-calling loop, capped by `max_iterations`). Aggregation rule: **sum tokens across iterations, then divide once**. Concretely:
  ```
  ratio = sum(cache_read_tokens) / (sum(cache_read_tokens) + sum(cache_creation_tokens))
  ```
  This is a token-weighted measure that matches how Anthropic actually bills cached input tokens. Iteration 1 (cold write → 0% hit) and iteration 2 (warm read → 100% hit) blend proportionally to their token counts — not a misleading per-call mean.
- **D-06:** Cold-cache edge case (denominator = 0, i.e., `sum_read + sum_creation == 0`) is defined as `cache_efficiency_ratio = 0.0`. This is required by ROADMAP.md success criterion 2 ("a session with a cold cache ... produces `cache_efficiency_ratio: 0.0`"). Implementation must guard against ZeroDivisionError explicitly.
- **D-07:** Per-turn accumulation lives in a per-request scoped accumulator. Two implementation options the planner can choose between:
  - (a) Add a ContextVar in `core/context.py` (mirroring `correlation_id_ctx`), reset by the `correlation_id` middleware on each request, mutated inside `_agent_node` after each LLM call, read by the SSE generator at `done`.
  - (b) Add fields to `ChatState` (e.g., `cache_creation_tokens_total`, `cache_read_tokens_total`), mutated inside `_agent_node`, read from `final_state` in the SSE generator.
  Both are reasonable. ContextVar matches the existing correlation_id plumbing pattern; ChatState matches the LangGraph data-flow pattern and lifetimes. Planner picks based on which is less invasive given the streaming path's existing reads of `final_state`.

### Breadcrumb payload
- **D-08:** Breadcrumb category and shape:
  - `category="cache_metrics"` (or similar — planner's call, but consistent with Sentry breadcrumb conventions)
  - `level="info"`
  - `message="cache_efficiency"` (short identifier)
  - `data={"cache_efficiency_ratio": ratio, "cache_read_tokens": sum_read, "cache_creation_tokens": sum_creation, "iterations": n_agent_calls}`
  Including raw token counts and iteration count alongside the ratio costs nothing in payload size and makes the breadcrumb diagnosable on its own — no need to cross-reference logs to interpret a ratio of 0.0.
- **D-09:** Breadcrumb must be a **no-op when `SENTRY_ENABLED` is false** — same gate as `bind_sentry_scope` in `core/sentry.py`. Local dev / unit tests must not require Sentry.

### Verification and DEE-50 (OBS-02)
- **D-10:** The "measured cache hit rates from at least one production deployment" threshold is **a single warm-cache turn captured after deploy** — one `/chat/stream/agentic` request that produces a non-zero `cache_efficiency_ratio` in the breadcrumb. Matches the existing two-call manual verification from Phase 17. No multi-day baseline required as part of this phase (deferred — see `<deferred>`).
- **D-11:** DEE-50 update artifact is **a Linear comment** on the existing ticket — not a description edit, not a separate repo doc. The comment must contain three sections:
  1. **Eligible call sites** — copied/summarized from Phase 17/18 CONTEXT.md (ChatAgent tools cache breakpoint, ChatAgent system prompt, 6 fiqh module system prompts, classifier, translation, primer; plus the explicit exclusions: enhancer prompt + dynamic generator/hikmah_elaboration prompts).
  2. **Approach taken** — content-block format via `make_cached_system_message`, `cache_control` on last bound tool via `@tool(extras=...)`, observability via `_agent_node` breadcrumb at SSE `done`.
  3. **Measured hit rate** — the post-deploy `cache_efficiency_ratio` value(s) and a screenshot or quote of the Sentry breadcrumb.
- **D-12:** The DEE-50 update is **a manual step the user performs after deployment**. Phase 19 implementation work cannot complete the OBS-02 update because the measurement requires production traffic. The phase plan should treat OBS-02 as a documented post-deploy checklist item, not an executable task. The plan must state this explicitly so verification doesn't block on something that's deliberately external.

### Claude's Discretion
- Exact ContextVar name vs ChatState field names (D-07) — planner picks based on least-invasive integration.
- Exact breadcrumb `category` string and `message` string (D-08) — follow existing Sentry SDK conventions; no hard requirement.
- Whether to expose the helper that emits the breadcrumb in `core/sentry.py` (alongside `bind_sentry_scope`) or in a new module — `core/sentry.py` is the natural home.
- Whether tests should cover the breadcrumb emission via Sentry SDK mocking, or only assert the in-memory accumulator math — the success criteria are observable via Sentry breadcrumb data, but a unit-test seam on the accumulator math is cheap and faster than mocking Sentry.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements and Goals
- `.planning/ROADMAP.md` §Phase 19 — Goal, OBS-01/OBS-02 requirements, and all 3 success criteria (locked)
- `.planning/REQUIREMENTS.md` §Observability — OBS-01 (per-session ratio breadcrumb) and OBS-02 (DEE-50 update)

### Critical Context from Prior Phases
- `.planning/phases/17-chatagent-caching-foundation/17-CONTEXT.md` — Established `_agent_node` cache-metrics logging (D-05), `make_cached_system_message` helper, `response.response_metadata["usage"]` as the source of truth, never-cache-enhancer constraint, deferred `_generate_response_node` metrics
- `.planning/phases/18-module-prompt-restructuring/18-CONTEXT.md` — Established that `generator_messages` and `hikmah_elaboration_messages` use plain `SystemMessage` (dynamic prompts, no caching), and full list of refactored fiqh/classification/translation call sites — feeds DEE-50 "eligible call sites" content
- `.planning/research/PITFALLS.md` — CRITICAL-5 (`usage_metadata` double-counts cache tokens — use `response_metadata["usage"]`)

### Primary Change Files
- `agents/core/chat_agent.py` (`_agent_node`, lines 184-199) — already extracts `_cache_creation` and `_cache_read`; Phase 19 adds accumulation into a per-request scope (ContextVar or ChatState)
- `core/pipeline_langgraph.py` — five SSE `done` emission sites (lines 201, 219, 378, plus `done` after error paths) — breadcrumb fire site
- `core/sentry.py` — natural home for a `record_cache_metrics_breadcrumb(...)` helper alongside existing `bind_sentry_scope`; SENTRY_ENABLED guard already established
- `core/context.py` — only if D-07 option (a) is chosen (new ContextVar mirrors `correlation_id_ctx`)
- `agents/state/chat_state.py` — only if D-07 option (b) is chosen (two new int fields on ChatState)

### External
- Linear ticket DEE-50 — destination of the OBS-02 update comment (Linear is external; not a repo file). Memory note: all milestone commits in this repo are prefixed `DEE-50:` — see `.../memory/feedback_linear_commit_prefix.md`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `agents/core/chat_agent.py:184-199` — `_cache_creation` and `_cache_read` are already extracted from `response.response_metadata["usage"]`; Phase 19 only needs to accumulate them, not re-source them
- `core/sentry.py:bind_sentry_scope` — the SENTRY_ENABLED guard pattern; the new breadcrumb helper should mirror this (early return when disabled)
- `core/context.py:correlation_id_ctx` — established ContextVar pattern, reset per-request by middleware (Phase 13); a cache-tokens ContextVar would slot in identically
- `agents/state/chat_state.py` (`ChatState` TypedDict) — established fields like `iterations`, `errors`, `messages`; adding `cache_creation_tokens_total` / `cache_read_tokens_total` ints fits the existing schema

### Established Patterns
- Sentry SDK is initialized once in `core/sentry.py`; all Sentry-touching code paths must short-circuit when `SENTRY_ENABLED` is false (D-09)
- Logging convention from Phases 13–18: structured fields go in `extra={}` with `correlation_id` always present; the new breadcrumb call is parallel to that pattern but uses `sentry_sdk.add_breadcrumb` instead of `logger.*`
- LangGraph node mutation pattern: nodes read `state`, mutate `state[...]`, return state — Phase 19 follows this if D-07 option (b) is chosen
- The SSE generator already reads from `final_state.get(...)` after `compiled_graph.astream()` completes (`core/pipeline_langgraph.py:204` etc.) — natural read site for ChatState-based accumulator

### Integration Points
- The breadcrumb emission site needs access to: (a) the per-turn aggregate token counts, (b) the correlation_id (already in scope via `correlation_id_ctx.get()`), and (c) Sentry SDK. All three are available at the SSE generator's terminal `done` sites in `pipeline_langgraph.py` regardless of whether the accumulator is ContextVar- or ChatState-backed.
- `_agent_node` is the only writer to the accumulator; `_tool_node`, `_generate_response_node`, and the fiqh sub-graph nodes do NOT touch it.
- Existing tests in `agent_tests/test_prompt_cache.py` (Phase 17) verify cache write/read behavior — Phase 19 tests can extend this same pattern to assert the breadcrumb is fired with the expected ratio (or use a unit-level seam on the helper).

</code_context>

<specifics>
## Specific Ideas

- The breadcrumb `data` dict should include raw token counts and the iteration count alongside the ratio — diagnosing a `ratio=0.0` event without those is impossible, and they cost nothing.
- DEE-50 comment should literally cite the Phase 17 and Phase 18 CONTEXT.md "Primary Change Files" lists for the "eligible call sites" section — they're already accurate and complete; no need to re-derive.

</specifics>

<deferred>
## Deferred Ideas

- **Per-Redis-session multi-turn aggregation**: Roll cache metrics across all turns within a single durable session_id (Redis TTL = 12,000s). Would require a new persistence surface (Redis hash or DB table). Out of Phase 19 scope; revisit if per-turn breadcrumbs prove insufficient for understanding warm-cache reuse across follow-up questions.
- **`_generate_response_node` cache-metrics logging**: Phase 17 D-05 deferred this because the prompt is below the 2048-token Sonnet threshold today. Still deferred — revisit if/when the system prompt grows past the threshold.
- **Fiqh sub-graph cache-metrics logging**: All 6 fiqh module LLM calls received `make_cached_system_message` in Phase 18 but most are below the Haiku 4096 / Sonnet 2048 threshold. Wiring metrics there now would only emit zeros. Revisit when (a) those prompts grow, or (b) the model swap moves them above threshold.
- **Multi-day production baseline + post-redeploy comparison**: D-10 settled on a single warm-cache turn for OBS-02 closure. A more rigorous distribution-over-time measurement remains valuable but is post-Phase-19 observation work, not implementation work.
- **Sentry dashboard / alerting rules**: A breadcrumb is per-request data; dashboards or threshold alerts on `cache_efficiency_ratio` are a separate observability layer. Not in scope.
- **Cache cost dashboard / billing reconciliation**: Translating `cache_efficiency_ratio` into actual dollar savings requires Anthropic billing API integration. Out of scope.

</deferred>

---

*Phase: 19-Observability and Verification*
*Context gathered: 2026-05-03*
