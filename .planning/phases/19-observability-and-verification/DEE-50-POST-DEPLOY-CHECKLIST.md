# DEE-50 Post-Deploy Checklist (OBS-02 Closure)

**Status:** Required manual action — OBS-02 cannot be closed by automated tasks (D-12).
**Owner:** Developer who deploys Phase 19 to production.
**Trigger:** After Phase 19 (Plans 01 + 02 + 03 Task 1) ships and the next production deploy completes.

---

## Why this is manual

OBS-02 requires "measured cache hit rates from at least one production deployment" (ROADMAP Phase 19 success criterion 3).
Phase 19 implementation work cannot satisfy this requirement because the measurement requires production traffic against the live Anthropic API. Per CONTEXT.md D-10, the bar is **a single warm-cache turn captured after deploy** — one `/chat/stream/agentic` request that produces a non-zero `cache_efficiency_ratio` in the Sentry breadcrumb.

---

## Procedure

### Step 1: Verify deploy carries the Phase 19 changes

Confirm the deployed commit includes:
- `core/sentry.py:record_cache_metrics_breadcrumb` (Plan 01 Task 1)
- `agents/state/chat_state.py` cache_*_tokens_total fields (Plan 01 Task 2)
- `agents/core/chat_agent.py` `_agent_node` accumulation (Plan 02 Task 1)
- `core/pipeline_langgraph.py` `_emit_cache_metrics_breadcrumb` + 4 call sites (Plan 02 Task 2)

### Step 2: Trigger two identical chat turns

Send the same non-fiqh Islamic query twice via `/chat/stream/agentic` within 5 minutes (Anthropic's prompt cache TTL). Suggested query (matches `agent_tests/test_prompt_cache.py:_TEST_QUERY`):

> "What does Islam teach about the importance of seeking knowledge?"

Use any HTTP client; correlation IDs from the `X-Correlation-ID` response header on each response will identify the two turns in Sentry.

### Step 3: Observe breadcrumbs in Sentry

In Sentry, navigate to Issues -> any captured event from one of the two turns (filter by the response `X-Correlation-ID`). Open the breadcrumb trail. Locate the breadcrumb with:
- `category: cache_metrics`
- `message: cache_efficiency`
- `data` carrying `cache_efficiency_ratio`, `cache_read_tokens`, `cache_creation_tokens`, `iterations`

Expected:
- Turn 1 (cold): `cache_creation_tokens > 0`, `cache_read_tokens == 0`, `cache_efficiency_ratio == 0.0`
- Turn 2 (warm): `cache_read_tokens > 0`, `cache_efficiency_ratio > 0.0` (typically near 1.0 if no new context tokens were added between calls)

If the breadcrumb is absent: confirm `SENTRY_ENABLED=true` in the production env; confirm the deploy carries the Phase 19 commits.

If turn 2 shows `cache_efficiency_ratio == 0.0`: the cache was either evicted (>5 minutes between requests) or the request modified the cache key (a different system-prompt prefix, e.g. tool reordering). Re-run within the TTL window.

### Step 4: Post Linear comment on DEE-50

Copy the template below into a new comment on https://linear.app/.../DEE-50 (Linear UI; not the Linear API per D-11). Replace `<...>` placeholders with the observed values from Step 3.

---

## Linear comment template (copy verbatim, fill in `<...>`)

> **OBS-02: Cache implementation summary and measured hit rate**
>
> ### Eligible call sites
>
> **ChatAgent path (Phase 17 — CACHE-01..04, STRUCT-01):**
> - ChatAgent tools cache breakpoint — `cache_control` injected via `@tool(extras=...)` on `retrieve_quran_tafsir_tool` (last bound tool); `agents/tools/retrieval_tools.py`.
> - ChatAgent system prompt — `make_cached_system_message(AGENT_SYSTEM_PROMPT)` at `agents/core/chat_agent.py:_agent_node` (line ~178) and `_generate_response_node` (line ~271).
>
> **Module prompts (Phase 18 — STRUCT-02):**
> - 6 fiqh module system prompts (static, cacheable): `modules/fiqh/classifier.py`, `refiner.py`, `sea.py`, `generator.py`, `decomposer.py`, `filter.py`.
> - Classification — `modules/classification/classifier.py` via `core/prompt_templates.py:fiqh_classifier_messages` and `nonislamic_classifier_messages` builders (static).
> - Translation — `modules/translation/translator.py` via `core/prompt_templates.py:translation_messages` builder (static).
> - Primer generation — `services/primer_service.py` via `core/prompt_templates.py:primer_messages` builder (static; system body has only escaped braces).
>
> **Explicit exclusions:**
> - `modules/enhancement/enhancer.py` — Haiku 4.5 requires 4096-token minimum; enhancer prompt is ~330 tokens (guaranteed cost increase, zero hits).
> - `core/prompt_templates.py:generator_messages` — system body embeds runtime `{target_language}` and `{references}`; caching dynamic content writes a new entry every call.
> - `core/prompt_templates.py:hikmah_elaboration_messages` — system body embeds 5 runtime variables; same dynamic-content reason.
> - ChatAgent `_generate_response_node` cache metrics — deferred (Phase 17 D-05); current prompt is below the 2048-token Sonnet threshold, so metrics would be all-zero noise.
> - Fiqh sub-graph cache metrics — deferred; most fiqh module prompts are below threshold today.
>
> ### Approach taken
>
> - Content-block format: every cacheable system prompt constructed via `core/chat_models.py:make_cached_system_message(text)` returning `SystemMessage(content=[{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}])`. This avoids the silent `cache_control` stripping in `ChatPromptTemplate.from_messages` (GitHub #26701).
> - Tool prefix: `cache_control: {"type": "ephemeral"}` on the LAST bound tool only (Anthropic's tools-prefix cache model). Achieved via `@tool(extras=...)` decorator — no change to `bind_tools()` call.
> - Metrics source: `response.response_metadata["usage"]` (raw Anthropic dict) — NEVER `response.usage_metadata` (LangChain double-counts cached tokens on streaming, GitHub #32818).
> - Per-turn observability: ChatState fields `cache_creation_tokens_total` and `cache_read_tokens_total` accumulate across `_agent_node` iterations; ratio computed once at the SSE `done` boundary in `core/pipeline_langgraph.py:_emit_cache_metrics_breadcrumb`; Sentry breadcrumb fired via `core/sentry.py:record_cache_metrics_breadcrumb` (no-op when `SENTRY_ENABLED=false`).
>
> ### Measured hit rate
>
> Production deploy: `<deploy commit SHA / date>`
> Verification trigger: two identical `/chat/stream/agentic` requests within 5 minutes
>
> | Turn | correlation_id | cache_creation_tokens | cache_read_tokens | cache_efficiency_ratio | iterations |
> |------|----------------|----------------------:|------------------:|-----------------------:|-----------:|
> | 1 (cold) | `<uuid>` | `<int>` | 0 | 0.0 | `<int>` |
> | 2 (warm) | `<uuid>` | `<int>` | `<int>` | `<float>` | `<int>` |
>
> Sentry breadcrumb screenshot: `<attached image OR Sentry permalink>`
>
> Cache prefix established and read-back confirmed.

---

## Closure

When the Linear comment is posted with all `<...>` filled in:
- Update `.planning/STATE.md` to mark OBS-02 verified
- Update `.planning/ROADMAP.md` Phase 19 success criterion 3 status to met
- Mark Phase 19 complete

This file may then be removed or archived (it is a one-shot checklist).
