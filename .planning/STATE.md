---
gsd_state_version: 1.0
milestone: v1.4
milestone_name: LLM Input Caching
status: SHIPPED — v1.4 archived 2026-05-04; OBS-02 pending post-deploy observation; ready for /gsd-new-milestone
stopped_at: v1.4 milestone complete (2026-05-04)
last_updated: "2026-05-04T00:00:00.000Z"
last_activity: 2026-05-04 — v1.4 milestone archived; 3 phases, 9 plans complete; deploying to production
progress:
  total_phases: 3
  completed_phases: 3
  total_plans: 9
  completed_plans: 9
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-04 after v1.4 milestone archived)

**Core value:** Every fiqh answer must be strictly grounded in retrieved evidence from Ayatollah Sistani's published rulings — the system refuses to answer rather than hallucinate or speculate.
**Current focus:** v1.4 SHIPPED — run `/gsd-new-milestone` to start v1.5

## Current Position

Milestone v1.4 complete — all 3 phases, 9 plans shipped.
Next: `/gsd-new-milestone` to define v1.5 requirements and roadmap.
Status: v1.4 milestone complete — OBS-02 human action required after next deploy
Last activity: 2026-07-22 — Completed quick task 260722-ffh: DEE-69 per-language hikmah lessons + quiz (lesson_translations sidecar + sync read-time projection + offline build-not-run MT job; 27 new tests pass, verified 7/7)

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
| 260509-r51 | DEE-51 chatbot error resilience + observability (Anthropic/Pinecone retries + Sentry-visible logging) | 2026-05-09 | e110e03 | Complete | [260509-r51-dee-51-error-resilience-and-logging](./quick/260509-r51-dee-51-error-resilience-and-logging/) |
| 260509-3cd | Real-time fiqh SSE status events — eliminate the 10-15s silent gap during fiqh sub-graph execution | 2026-05-10 | 94a06d4 | Complete | [260509-3cd-realtime-fiqh-sse-status-events](./quick/260509-3cd-realtime-fiqh-sse-status-events/) |
| 260510-qcx | Fix primer stream CancelledError handling — stop Sentry from capturing benign SSE client disconnects | 2026-05-10 | 8f03c25 | Complete | [260510-qcx-fix-primer-stream-cancellederror-handlin](./quick/260510-qcx-fix-primer-stream-cancellederror-handlin/) |
| 260530-ddo | Skip quiz pages in hikmah upsert, attach MCQs to last text page, fix meta.total_pages count | 2026-05-30 | 64e3635 | Complete | [260530-ddo-skip-quiz-pages-in-hikmah-upsert-attach-](./quick/260530-ddo-skip-quiz-pages-in-hikmah-upsert-attach-/) |
| 260629-ia2 | Fix DEE-55 Ask Deen over-refusal on short meaningful selected text | 2026-06-29 | 14b6480 | Complete | [260629-ia2-fix-dee-55-ask-deen-over-refusal-on-shor](./quick/260629-ia2-fix-dee-55-ask-deen-over-refusal-on-shor/) |
| 260701-j8v | Improve chatbot personality: warmer voice, dynamic non-Islamic refusal, casual-message handling (DEE-12) | 2026-07-01 | 3c376a5 | Verified | [260701-j8v-improve-chatbot-personality-warmer-answe](./quick/260701-j8v-improve-chatbot-personality-warmer-answe/) |
| 260707-hyu | DEE-68 multilingual chatbot response quality — fix non-streaming path to honor target_language + deterministic language-injection tests + opt-in real_llm 6-language eval harness | 2026-07-07 | 3e65bc9 | Verified | [260707-hyu-dee-68-multilingual-chatbot-response-qua](./quick/260707-hyu-dee-68-multilingual-chatbot-response-qua/) |
| 260707-pxt | DEE-67 reference-lookup selected-language translations — Postgres sidecar table + join-after-retrieval enrichment (/references + SSE) + offline build-not-run batch MT job (personal key / Sonnet 5) | 2026-07-08 | cfc65d7 | Verified (migration pending live apply) | [260707-pxt-dee-67-reference-lookup-selected-languag](./quick/260707-pxt-dee-67-reference-lookup-selected-languag/) |
| 260708-ecy | DEE-67 follow-up: hold Quran MT out of translate_references.py via DISABLED_REF_TYPES guard (--ref-type all → hadith+tafsir only) + deterministic tests | 2026-07-08 | 1eec98f | Complete | [260708-ecy-dee-67-follow-up-disable-quran-mt-in-scr](./quick/260708-ecy-dee-67-follow-up-disable-quran-mt-in-scr/) |
| 260722-ffh | DEE-69 per-language hikmah tree lessons + quiz — lesson_translations field-level sidecar (PK entity_type/entity_id/field/language) + SYNC read-time projection into lessons/lesson-content/hikmah-trees + learner-facing quiz (EN/AR fallback) + offline build-not-run claude-CLI batch MT job (source_hash staleness; hardened Qur'an-preservation prompt — no structural marker exists) | 2026-07-22 | a73dd3c | Verified (migration pending live apply) | [260722-ffh-dee-69-per-language-hikmah-tree-lessons-](./quick/260722-ffh-dee-69-per-language-hikmah-tree-lessons-/) |

## Session Continuity

Last session: 2026-05-04
Stopped at: v1.4 milestone archived and tagged; deploying branch to production
Next action: After deploy, follow DEE-50-POST-DEPLOY-CHECKLIST.md to close OBS-02; then /gsd-new-milestone for v1.5
