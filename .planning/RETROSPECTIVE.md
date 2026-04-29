# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — Fiqh Agentic RAG MVP

**Shipped:** 2026-03-25
**Phases:** 4 | **Plans:** 12 | **Commits:** 78 (2026-03-23 → 2026-03-25)

### What Was Built

- **Ingestion pipeline:** PyMuPDF-based PDF parsing, ruling-boundary chunking (3000 chunks from 2796 Sistani rulings), BM25 sparse + dense embedding, dual Pinecone upsert
- **FAIR-RAG modules:** 6-category classifier, query decomposer, hybrid RRF retriever, evidence filter, SEA (structured evidence assessment), query refiner, answer generator — all unit-tested with mocked LLM
- **Coordinator + sub-graph:** Pure Python FAIR-RAG coordinator (max-3-iteration loop) wrapped in a LangGraph sub-graph invoked by the main ChatAgent, with session isolation via `checkpointer=False`
- **SSE integration:** Fiqh path detection in `pipeline_langgraph.py` with pre-canned status events, token-by-token streaming, and `fiqh_references` SSE event
- **39 requirements satisfied, 5 E2E flows verified, 0 blockers at ship**

### What Worked

- **Phased isolation:** Building modules in isolation (Phase 3) with mocked LLM tests before wiring (Phase 4) caught interface issues early without needing live infra
- **Sub-graph composition:** LangGraph `checkpointer=False` pattern cleanly solved the session isolation requirement without custom state management
- **Dynamic LLM allocation pattern:** Routing gpt-4o-mini for classification/SEA and gpt-4.1 for generation/refinement kept costs low while maintaining quality
- **BM25 JSON serialization:** Persisting BM25 encoder to `data/fiqh_bm25_encoder.json` (not pickle) made it portable across ingestion and query-time environments
- **Fails-open evidence filtering:** Returning all docs when the filter LLM returns an empty list prevented silent context loss

### What Was Inefficient

- **ROADMAP.md progress table went stale:** Phase 2 showed "Not started" and Phase 3 showed "In Progress" at archive time despite all work being complete — the progress table needs updating at each plan completion, not just at phase start
- **Pre-canned SSE status events:** The decision to emit pre-canned `fiqh_refine` events (instead of reading live `FiqhState.status_events`) deferred a real UX accuracy problem to tech debt; the clean solution existed but was skipped for speed
- **Phase 02-01/02-02 SUMMARY.md missing one_liner field:** Two summary files lacked the `one_liner` frontmatter field, causing "One-liner:" placeholders to appear in MILESTONES.md from the CLI tool

### Patterns Established

- **Wrapper node pattern:** `_call_fiqh_subgraph_node` projects `ChatState → FiqhState → ChatState` without sharing keys between schemas — clean interface for sub-graph composition
- **Fails-open for LLM tools:** When LLM output is ambiguous or empty, return all input docs rather than filtering aggressively — better to over-include than silently drop evidence
- **No module-level env var guards for optional features:** Guard inside the function/script, not at import time, to avoid breaking server startup for developers without fiqh indexes configured
- **Mock-first unit tests for pipeline modules:** All FAIR-RAG modules have `unittest.mock.patch` tests that run without LLM or Pinecone — enables fast CI and clear interface contracts

### Key Lessons

1. **Sub-graph state isolation requires explicit design:** LangGraph's MemorySaver checkpointer persists across invocations by default — always set `checkpointer=False` for sub-graphs that must be stateless per request
2. **Chunk count from research papers may not match your PDF:** Expected 1000–1600 chunks per FAIR-RAG paper assumptions; actual PDF produced 3000 chunks (2796 unique rulings). Always verify before committing to index sizing
3. **The "One-liner" frontmatter field in SUMMARY.md is load-bearing:** The milestone CLI depends on it; files missing this field silently produce placeholder text in MILESTONES.md
4. **ROADMAP.md progress table requires active maintenance:** It's not auto-updated by gsd-tools — mark phases complete in the table at the end of each plan execution, not just at phase start

### Cost Observations

- Model mix: Sonnet 4.6 (primary executor across all phases)
- Sessions: ~78 commits over 2 days
- Notable: Dynamic LLM allocation (gpt-4o-mini for 60%+ of inference steps) achieved research-validated 13% cost savings vs all-large allocation; fast iteration over 2 days suggests good session continuity

---

## Milestone: v1.1 — Supabase Migration

**Shipped:** 2026-04-07
**Phases:** 3 | **Plans:** 6 | **Commits:** ~30 (2026-04-06 → 2026-04-07)

### What Was Built

- **Database migration:** Supabase Postgres provisioned; genesis Alembic migration created to support fresh-DB provisioning; all 13 tables + pgvector HNSW index verified; app connects via SQLAlchemy with zero code changes
- **Auth migration:** JWKS fetch URL updated from Cognito to `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`; Cognito env vars removed; account deletion replaced with httpx Supabase Admin API call; all routes protected with strict auth + ENV=development bypass
- **Cleanup:** boto3 fully removed from requirements.txt and api/account.py; `.env.example` created with 28 vars grouped by service; README `## Environment Variables` section added with v1.0→v1.1 migration callout

### What Worked

- **Clear phase boundaries:** Keeping auth changes in Phase 6 and boto3 removal in Phase 7 prevented scope creep and made each phase independently verifiable
- **Genesis migration pattern:** Creating `0000_initial_schema.py` as a separate foundational migration (rather than hacking existing migrations) kept the Alembic chain clean and idempotent — `alembic upgrade head` on any fresh DB now just works
- **Research catching subtle issues:** Phase 7 researcher identified the botocore import line that CONTEXT.md missed — both lines got removed cleanly
- **Plan checker catching gaps:** Checker caught 4 missing env vars in .env.example template before execution — saved a re-run

### What Was Inefficient

- **Requirements checkboxes not updated during execution:** DB-01, DB-02, DB-03, AUTH-01, AUTH-02 remained unchecked at milestone close despite the code being complete; checkbox maintenance needs to happen at plan completion, not retroactively
- **Phase 5 was purely manual (infra provisioning):** The GSD execution flow doesn't map cleanly to "go click in a dashboard" tasks — Phase 5 plans were more of a checklist than executable code tasks

### Patterns Established

- **Genesis migration for legacy codebases:** When adopting Alembic on a codebase with pre-existing tables, always create a `0000_initial_schema.py` genesis migration before running against any fresh database
- **Direct port 5432 over pooler:** asyncpg + Supabase transaction pooler (6543) are incompatible — always use direct connection for both sync and async SQLAlchemy engines
- **.env.example as the deployment contract:** A well-structured `.env.example` grouped by service (OpenAI, Pinecone, Supabase, Redis, App) eliminates all "what env vars do I need?" onboarding friction

### Key Lessons

1. **Alembic chain must be validated on a fresh DB before any migration milestone ships** — testing only on existing databases hides genesis-migration gaps
2. **Requirement checkboxes are a tracking artifact, not just a gate** — update them at plan completion so they reflect reality at archive time
3. **Auth middleware migrations are less risky than they look** — changing a JWKS URL is a one-line diff with no schema or protocol impact; the testing surface is the JWKS fetch at startup

### Cost Observations

- Model mix: Sonnet 4.6 (all phases)
- Sessions: ~2 sessions over 2 days
- Notable: Phase 5 (infra provisioning) generated minimal commits — most of the work was manual Supabase dashboard interaction; GSD planning overhead was low relative to v1.0

---

## Milestone: v1.2 — Claude Migration

**Shipped:** 2026-04-10
**Phases:** 5 | **Plans:** 9 | **Commits:** 71 (2026-03-27 → 2026-04-10)

### What Was Built

- **Config + Dependencies (Phase 8):** ANTHROPIC_API_KEY wired into startup guard; langchain-anthropic + anthropic added; openai + langchain-openai removed; LLM and embedding defaults updated
- **LLM Swap (Phase 9):** ChatAnthropic replaces init_chat_model/OpenAI in all 4 factory functions; Claude-specific fixes applied: preamble-safe fiqh classifier via `with_structured_output`, AIMessage filter in `_agent_node`, ModelConfig temperature constraint ≤1.0
- **Embedding Migration (Phase 10):** HuggingFace `all-mpnet-base-v2` (768-dim, free, no API key) replaces text-embedding-3-small (1536-dim); Alembic migration drops + recreates pgvector tables with Vector(768); backfill script created
- **Dead Code Cleanup (Phase 11):** All OpenAI import sites, OPENAI_API_KEY shim, and voyageai dependency excised; 197 tests pass with zero OpenAI references in application code
- **Docs Cleanup (Phase 12):** All user-facing docs, comments, and docstrings updated; README/DEPLOYMENT/CHATBOT reflect Claude + HuggingFace; stale comment strings in pipeline.py and docstrings in decomposer.py + README_LANGGRAPH fixed

### What Worked

- **Phased provider swap:** Tackling config (Phase 8), LLM (Phase 9), embedding (Phase 10), dead code (Phase 11) in sequence prevented contamination — each phase had a clean, verifiable scope
- **Milestone audit before Phase 12:** Running `/gsd:audit-milestone` before the final phase surfaced all remaining tech debt items; Phase 12 then closed them in a single targeted plan
- **`with_structured_output` for preamble-safe parsing:** Claude returns preamble text before JSON; using Pydantic structured output via LangChain bypassed all fragile string parsing and was simpler than string manipulation
- **HuggingFace pivot discovery:** The research phase for Phase 10 identified that `all-mpnet-base-v2` was already installed — switching to it from Voyage AI saved an API key dependency and ongoing cost with zero retrieval quality trade-off at the index sizes used
- **Verification gap closed inline:** Phase 12 verifier found 1 gap (README_LANGGRAPH footer) after initial execution; fixed inline and re-verified without a full gap-closure cycle — single-line fixes don't need a plan

### What Was Inefficient

- **Voyage AI planned, then dropped:** Phase 8 wired `VOYAGE_API_KEY`; Phase 10 removed it in favour of HuggingFace. The pivot was correct but created two superseded requirements (CONF-02, CONF-04) with misleading descriptions. Better: decide on the final embedding provider before Phase 8 rather than updating it in Phase 10.
- **Phase 9 VERIFICATION.md body/frontmatter discrepancy:** The verifier updated frontmatter to `status: passed` but left body text saying `gaps_found` — this surfaced as tech debt in the milestone audit and required Phase 12 to reconcile it. Verifier should update both frontmatter and body in one pass.
- **SUMMARY.md `one_liner` field extraction gaps:** Phase 8 and 10 summaries lacked clean `one_liner` frontmatter, producing "One-liner:" placeholders in MILESTONES.md. Same pattern seen in v1.0 — still not fixed in the executor.

### Patterns Established

- **Provider swap order:** Config vars → LLM wiring → Embedding migration → Dead code → Docs. Each step is independently verifiable and doesn't require the next to be done first.
- **`with_structured_output` for any enum-valued LLM call:** Use it whenever a node expects a fixed-vocabulary output from Claude. It eliminates preamble parsing, JSON parsing, and validation in one change.
- **AIMessage filter before LLM invocation:** Claude errors on consecutive tool-call messages without an intermediate assistant turn. Filter `state["messages"]` before passing to `llm.invoke()` in any LangGraph agent node.
- **Milestone audit before cleanup phase:** Run `/gsd:audit-milestone` after the last functional phase (before the cleanup phase) to capture all accumulated tech debt. The cleanup phase then has a concrete, complete list rather than relying on memory.

### Key Lessons

1. **Decide on all external providers before Phase 1 of a migration** — mid-milestone pivots (Voyage AI → HuggingFace) are correct but leave superseded requirements and stale plan context
2. **VERIFICATION.md body and frontmatter must be reconciled in the same commit** — if the verifier updates frontmatter without updating the body, the discrepancy becomes tech debt that has to be cleaned up later
3. **Single-line gap fixes don't need a gap-closure plan** — verify, fix inline, re-verify. The workflow overhead of plan→execute→verify for one line of markdown is wasteful.
4. **Claude's temperature constraint (≤1.0) is different from OpenAI's (≤2.0)** — LangChain's ModelConfig validator set `le=2.0` for OpenAI; this must be updated to `le=1.0` in any OpenAI→Claude migration

### Cost Observations

- Model mix: Sonnet 4.6 (all executor and verifier agents)
- Sessions: ~3 sessions, 71 commits over 14 days
- Notable: Inline gap closure (Phase 12 verifier found 1 gap; fixed in main context without spawning another executor) saved ~1 agent spawn; verification cycle was verifier → inline fix → re-verify

---

## Milestone: v1.3 — Sentry Deep Integration

**Shipped:** 2026-04-28
**Phases:** 4 | **Plans:** 8 | **Timeline:** 2026-04-26 → 2026-04-28 (3 days)

### What Was Built

- **Phase 13 (Infrastructure):** `core/context.py` (correlation_id ContextVar), `core/middleware.py` (CorrelationIdMiddleware, server-side UUID), `core/sentry.py` (dual-gate init, `bind_sentry_scope`, `_scrub_pii` before_send hook); main.py wired with side-effect import
- **Phase 14 (Routes):** All 4 main API routes instrumented with `extra={}` structured logging, `bind_sentry_scope()`, zero `print()` calls; REF-02 data-leak bug closed (raw exception was being returned in HTTP 500 detail)
- **Phase 15 (Pipeline + Tools):** `core/pipeline_langgraph.py`, `agents/tools/retrieval_tools.py`, `agents/core/chat_agent.py` — ~30 `print()` calls replaced; node traversal at DEBUG; zero `capture_exception()` calls
- **Phase 16 (Fiqh Sub-graph):** 10 `%s`-format log calls converted to `extra={}` in `agents/fiqh/fiqh_graph.py`; 3 new WARNING boundaries at FAIR-RAG silent failure paths; 7 unit tests via TDD (RED → GREEN commits)

### What Worked

- **Single-file-per-plan scoping:** Each plan targeted 1–2 files, making verification fast and unambiguous — grep checks were pass/fail without interpretation
- **Decision pre-locking in CONTEXT.md:** Phase 16 pre-locked all decisions (D-01..D-11) before execution — no discretionary choices during execution, zero deviations from plan
- **TDD for instrumentation tests:** Writing failing tests first (Phase 16 RED commit) made the WARNING boundary conditions explicit before implementation, and the GREEN commit verified all 3 boundaries exactly
- **Side-effect import pattern for Sentry init:** `import core.sentry` in main.py instead of inline `sentry_sdk.init()` — clean separation of concerns, single-responsibility module, guaranteed one-fire via `sys.modules` caching
- **logger.error(exc_info=True) over capture_exception():** Eliminated a whole class of duplicate Sentry event bugs before they could occur

### What Was Inefficient

- **REQUIREMENTS.md not updated during execution:** 17 of 22 requirements remained unchecked at milestone close despite all being delivered — same pattern seen in v1.1 and v1.2. Checkbox maintenance needs to happen at plan completion, not retroactively at archive time.
- **ROADMAP.md Phase 16 progress inconsistency:** Phase 16 plan checkbox and progress table went stale during execution — discovered only at archive time. Same root cause as the requirements gap: progress artifacts not updated at plan completion.
- **No formal milestone audit file:** `/gsd-audit-milestone` was not run before archival — proceeded on evidence from SUMMARY.md files instead. Acceptable for an observability-only milestone with no behavior changes, but the audit adds value for functional milestones.

### Patterns Established

- **WARNING-on-boundary pattern:** Log `logger.warning()` BEFORE continuing on a silent failure path, not instead of continuing. The fail-open path still executes; the warning makes the failure visible in Sentry. Applied in FIQH-02, FIQH-03, FIQH-04.
- **Patch deferred imports at source module:** For unit tests patching functions imported in fiqh_graph.py, patch at the source module (`modules.fiqh.xxx`) not at the consumer module level — Pitfall 6 from Phase 16 research.
- **`query_length` instead of `query` in log extra={}:** Log the length of user content (an int) rather than the content itself — prevents Islamic query text reaching Sentry Logs at all, satisfying the Article 9 compliance requirement without needing a `before_send_log` hook.

### Key Lessons

1. **REQUIREMENTS.md checkbox maintenance must happen at plan completion** — three consecutive milestones (v1.1, v1.2, v1.3) had unchecked-but-delivered requirements at archive time. The pattern is now documented; the fix is to check off requirements in REQUIREMENTS.md as part of the plan execution self-check.
2. **Pre-lock all instrumentation decisions in CONTEXT.md before Phase execution** — Phase 16 with pre-locked D-01..D-11 had zero deviations and took 7 minutes. Phase 15 without the same pre-locking had the same result but required more judgment calls during execution.
3. **Duplicate Sentry events are a silent bug** — `capture_exception()` AND `logger.error(exc_info=True)` both captured the same exception in the original `catch_exceptions_mw`; LoggingIntegration is invisible and easy to forget. Document the rule in CONTEXT.md for any future instrumentation phase.
4. **The `before_send` hook is not a substitute for not logging PII** — `before_send` removes request body, but Sentry Logs (structured log events) bypass it. The correct approach is to never include `user_query` or query content in any `extra={}` dict — the hook is a second layer, not the first.

### Cost Observations

- Model mix: Sonnet 4.6 (all phases)
- Sessions: ~3 days, 14 feature commits + supporting test/docs commits
- Notable: Observability-only milestone with no behavior changes — fastest milestone at 3 days; phasing by file/layer (infra → routes → pipeline → fiqh) worked cleanly

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 4 | 12 | First milestone; established FAIR-RAG module isolation + sub-graph patterns |
| v1.1 | 3 | 6 | Infrastructure migration; established genesis-migration + direct-connection patterns |
| v1.2 | 5 | 9 | Provider migration; established provider-swap ordering + `with_structured_output` + AIMessage filter patterns |
| v1.3 | 4 | 8 | Observability pass; established WARNING-on-boundary + pre-locked CONTEXT.md + TDD for instrumentation patterns |

### Cumulative Quality

| Milestone | Tests Added | Modules | Zero-Dep Additions |
|-----------|-------------|---------|-------------------|
| v1.0 | ~55 mock-based unit tests | 8 fiqh modules | modules/fiqh/ (fully isolated from agents layer) |
| v1.1 | 0 new tests (infra migration) | 0 new modules | core/auth.py, api/account.py, .env.example |
| v1.2 | ~15 updated tests (HuggingFace mocks) | 0 new modules | langchain-anthropic (added), openai/langchain-openai/voyageai (removed) |
| v1.3 | 7 new unit tests (WARNING boundaries) | 3 new core modules | core/context.py, core/middleware.py, core/sentry.py; tests/test_fiqh_graph_logging.py |

### Top Lessons (Verified Across Milestones)

1. Build and test modules in isolation before wiring into the graph — Phase 3 isolation caught interface bugs before Phase 4 integration
2. Pre-canned workarounds for SSE/event propagation accrue UX debt — invest in proper event propagation at design time
3. Always validate Alembic chain on a fresh database before any migration milestone — the genesis-migration gap in v1.1 was only discovered during Phase 5 execution
4. Decide on all external providers before Phase 1 of a migration — mid-milestone pivots are correct but create superseded requirements and stale documentation
5. Run `/gsd:audit-milestone` before the final cleanup phase — surfaces all accumulated tech debt so the cleanup phase has a complete, authoritative list
6. **REQUIREMENTS.md checkbox maintenance must happen at plan completion** — three consecutive milestones had unchecked-but-delivered requirements at archive time; update checkboxes in REQUIREMENTS.md as part of plan self-check
7. **Pre-lock instrumentation decisions in CONTEXT.md before execution** — Phase 16 with pre-locked D-01..D-11 took 7 minutes and had zero deviations; the pattern scales to any phase with many small judgment calls
8. **`logger.error(exc_info=True)` is the only correct Sentry capture path** — `capture_exception()` creates duplicate events when LoggingIntegration is active; document this constraint in every future instrumentation CONTEXT.md
