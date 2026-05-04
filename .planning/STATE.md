---
gsd_state_version: 1.0
milestone: v1.4
milestone_name: LLM Input Caching
status: Phase 18 complete — ready for /gsd-discuss-phase 19 or /gsd-plan-phase 19
stopped_at: Phase 18 verified and closed (2026-05-03)
last_updated: "2026-05-03T00:00:00.000Z"
last_activity: 2026-05-03 — Phase 18 complete (3/3 plans, verified, one missed call site hotfix)
progress:
  total_phases: 3
  completed_phases: 2
  total_plans: 9
  completed_plans: 9
  percent: 67
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-28 after v1.3 milestone archived)

**Core value:** Every fiqh answer must be strictly grounded in retrieved evidence from Ayatollah Sistani's published rulings — the system refuses to answer rather than hallucinate or speculate.
**Current focus:** v1.4 LLM Input Caching — Phase 18 complete, Phase 19 (Observability and Verification) is next

## Current Position

Phase: 19 — observability-and-verification (CONTEXT NOT YET GATHERED)
Plan: None yet (discuss or plan next)
Status: Phase 18 complete — ready for Phase 19
Last activity: 2026-05-03 — Phase 18 verified; hotfix committed for missed _prompt→_build_messages call site in _generate_fiqh_response_node

Progress bar: `▓▓▓▓▓▓░░░░` 67% (2/3 phases complete)

## Performance Metrics

| Metric | v1.0 | v1.1 | v1.2 | v1.3 | v1.4 |
|--------|------|------|------|------|------|
| Phases | 4 | 3 | 5 | 4 | 3 |
| Plans | 12 | 6 | 9 | 8 | 9 |
| Requirements | 39 | 8 | 23 | 22 | 8 |

## Accumulated Context

### Decisions

All decisions logged in PROJECT.md Key Decisions table.

### v1.4 Phase Structure

| Phase | Focus | Requirements | Status |
|-------|-------|--------------|--------|
| 17 | ChatAgent Caching Foundation | CACHE-01, CACHE-02, CACHE-03, CACHE-04, STRUCT-01 | Complete |
| 18 | Module Prompt Restructuring | STRUCT-02 | Complete |
| 19 | Observability and Verification | OBS-01, OBS-02 | Next |

### Key Constraints for v1.4

- CACHE-01 and CACHE-02 must be implemented together — system prompt alone (1,427 tokens) is below the 2,048-token minimum; only clears the threshold when combined with tool definitions (~3,722 tokens) as a single cached prefix
- STRUCT-01 (make_cached_system_message helper) must exist before STRUCT-02 call sites can be refactored — Phase 17 delivers the helper, Phase 18 uses it
- Never cache `modules/enhancement/enhancer.py` — Haiku 4.5 requires 4,096-token minimum; enhancer prompt is ~330 tokens; caching would guarantee cost increase with zero hits
- Never put `cache_control` inside `ToolMessage.content[]` — causes `invalid_cache` API error (GitHub #34920)
- Use `response.response_metadata["usage"]` (raw Anthropic dict) for cache metrics, not `response.usage_metadata` — LangChain wrapper double-counts cached tokens on streaming calls (GitHub #32818)
- `AnthropicPromptCachingMiddleware` does not exist in `langchain-anthropic==0.3.22` — do not attempt to import it
- `ChatPromptTemplate.format_messages()` silently strips `cache_control` — all system prompts must use `SystemMessage(content=[...])` content-block lists (GitHub #26701)

### Phase 18 Decisions (for Phase 19 context)

- `generator_messages` and `hikmah_elaboration_messages` use plain `SystemMessage` (not `make_cached_system_message`) — their system bodies contain runtime variables, so caching would be a guaranteed miss every call (D-05)
- `enhancer` templates excluded — Haiku 4.5 requires 4,096-token minimum; enhancer prompt is ~330 tokens
- `with_redis_history` removed from `stream_generator.py` — replaced with explicit `make_history(session_id).messages` fetch + direct `model.stream()`
- `pipeline_langgraph.py` imports `_build_messages` as `fiqh_build_messages` (not the old `_prompt` alias)
- `_generate_fiqh_response_node` in `chat_agent.py` also needed updating (missed in 18-02, hotfixed after verification)

### Pending Todos

None.

### Blockers/Concerns

- Exact combined token count for ChatAgent (tools + system prompt) is estimated at ~5,149 — must be measured with tiktoken or Anthropic token counter as first implementation step in Phase 17 to confirm caching eligibility
- `langchain-anthropic` version bump from 0.3.22 to 0.3.25 carries compatibility risk with `langchain==0.3.27` — leave at 0.3.22 until explicitly verified

### Quick Tasks Completed

| # | Description | Date | Commit | Status | Directory |
|---|-------------|------|--------|--------|-----------|
| 260420-t2v | Improve SSE status granularity in /stream/agentic endpoint | 2026-04-21 | 54c8418 | Verified | [260420-t2v-improve-sse-status-granularity-in-stream](./quick/260420-t2v-improve-sse-status-granularity-in-stream/) |
| 260421-uma | Set up Sentry SDK for error tracking and structured logging | 2026-04-22 | fe61762 | Complete | [260421-uma-set-up-sentry-sdk-for-error-tracking-and](./quick/260421-uma-set-up-sentry-sdk-for-error-tracking-and/) |
| 260422-qau | Build feedback API to capture chatbot responses | 2026-04-22 | 760cb05 | Verified | [260422-qau-build-feedback-api-to-capture-chatbot-re](./quick/260422-qau-build-feedback-api-to-capture-chatbot-re/) |

## Session Continuity

Last session: 2026-05-03
Stopped at: Phase 18 verified and closed
Next action: /gsd-discuss-phase 19 (or /gsd-plan-phase 19 if context is clear)
