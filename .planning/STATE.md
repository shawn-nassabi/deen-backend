---
gsd_state_version: 1.0
milestone: v1.4
milestone_name: LLM Input Caching
status: Phase 17 structurally verified — run `python agent_tests/test_prompt_cache.py` to confirm live cache hits
stopped_at: Phase 17 verification complete (5/5 criteria verified, live test pending)
last_updated: "2026-05-03T21:45:00.000Z"
last_activity: 2026-05-03 — Phase 17 verified (5/5 criteria), awaiting live API test
progress:
  total_phases: 7
  completed_phases: 0
  total_plans: 3
  completed_plans: 3
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-28 after v1.3 milestone archived)

**Core value:** Every fiqh answer must be strictly grounded in retrieved evidence from Ayatollah Sistani's published rulings — the system refuses to answer rather than hallucinate or speculate.
**Current focus:** v1.4 LLM Input Caching — roadmap defined, ready to plan Phase 17

## Current Position

Phase: 17 — chatagent-caching-foundation (verified)
Plan: 17-03 (all plans done, verification complete)
Status: Phase 17 structurally verified — live API test pending
Last activity: 2026-05-03 — Phase 17 verification complete (5/5)

Progress bar: `▓░░░░░░░░░` 0% (0/3 phases complete — Phase 17 awaiting live test confirmation)

## Performance Metrics

| Metric | v1.0 | v1.1 | v1.2 | v1.3 | v1.4 |
|--------|------|------|------|------|------|
| Phases | 4 | 3 | 5 | 4 | 3 |
| Plans | 12 | 6 | 9 | 8 | TBD |
| Requirements | 39 | 8 | 23 | 22 | 8 |

## Accumulated Context

### Decisions

All decisions logged in PROJECT.md Key Decisions table.

### v1.4 Phase Structure

| Phase | Focus | Requirements | Depends on |
|-------|-------|--------------|------------|
| 17 | ChatAgent Caching Foundation | CACHE-01, CACHE-02, CACHE-03, CACHE-04, STRUCT-01 | Nothing |
| 18 | Module Prompt Restructuring | STRUCT-02 | Phase 17 (make_cached_system_message helper) |
| 19 | Observability and Verification | OBS-01, OBS-02 | Phase 17 (cache metrics flowing) |

### Key Constraints for v1.4

- CACHE-01 and CACHE-02 must be implemented together — system prompt alone (1,427 tokens) is below the 2,048-token minimum; only clears the threshold when combined with tool definitions (~3,722 tokens) as a single cached prefix
- STRUCT-01 (make_cached_system_message helper) must exist before STRUCT-02 call sites can be refactored — Phase 17 delivers the helper, Phase 18 uses it
- Never cache `modules/enhancement/enhancer.py` — Haiku 4.5 requires 4,096-token minimum; enhancer prompt is ~330 tokens; caching would guarantee cost increase with zero hits
- Never put `cache_control` inside `ToolMessage.content[]` — causes `invalid_cache` API error (GitHub #34920)
- Use `response.response_metadata["usage"]` (raw Anthropic dict) for cache metrics, not `response.usage_metadata` — LangChain wrapper double-counts cached tokens on streaming calls (GitHub #32818)
- `AnthropicPromptCachingMiddleware` does not exist in `langchain-anthropic==0.3.22` — do not attempt to import it
- `ChatPromptTemplate.format_messages()` silently strips `cache_control` — all system prompts must use `SystemMessage(content=[...])` content-block lists (GitHub #26701)

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

Last session: 2026-05-03T20:29:45.908Z
Stopped at: Phase 17 context gathered
Next action: /gsd-plan-phase 17
