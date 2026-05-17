# DEE-36 Async Migration — Manual Test Checklist

The automated pytest gates (see [async_baseline.md](async_baseline.md) and the
`tests/test_*_async*.py` files) cover concurrency behaviour, SSE event
ordering, and contextvar propagation against in-process stubs — no real
Anthropic / Pinecone / Redis / Postgres calls. This checklist is what
**must** be exercised against a real running server with real env vars
once all DEE-36 phases land.

Run against a server started with `docker compose up` or
`uvicorn main:app --reload`, with `.env` populated (`ANTHROPIC_API_KEY`,
`PINECONE_API_KEY`, real `REDIS_URL`, real Postgres `DATABASE_URL`,
`COGNITO_*`).

## Phase progress

| Phase | Linear | Status | What it shipped |
|---|---|---|---|
| Phase 0 | DEE-39 | merged | Concurrency baseline, stub fixtures, loadtest CLI |
| Phase 1 | DEE-40 | merged | `chain.stream` → `chain.astream` in streaming generators |
| Phase 2 | DEE-41 | merged | All ChatAgent nodes async; all `@tool` async; `agent.ainvoke()` |
| Phase 3 | DEE-42 | merged | Native `aclassify_*`, `aenhance_*`, `atranslate_*`, `aretrieve_*` |
| Phase 4 | DEE-43 | pending | Async Redis + `AsyncRedisChatMessageHistory` |
| Phase 5 | DEE-44 | pending | `/references`, `/hikmah/elaborate`, native async fiqh subgraph |
| Phase 6 | DEE-45 | pending | Async DB (asyncpg + AsyncSession) |
| Phase 7 | DEE-46 | pending | Final automated gates + sign-off |

## A. Real LLM streaming
- [ ] `curl -N -X POST http://127.0.0.1:8000/chat/stream/agentic -d '{"user_query":"What does Islam say about patience?","session_id":"manual-1"}'` — tokens stream in chunks, no buffering pause, complete in <10s.
- [ ] Same query in browser via the frontend — UI shows progressive token rendering, no "blank screen then dump".
- [ ] Long response (e.g. *"Tell me about the 12 Imams in detail"*) — streams cleanly without timeout.

## B. Real concurrency under prod-like config
- [ ] Open 5 simultaneous `curl -N` shells hitting `/chat/stream/agentic` with different `session_id` — all start emitting tokens within ~2s of each other (proves event-loop concurrency works against real Anthropic, not just stubs).
- [ ] `python scripts/loadtest_agentic.py --mode external --url <prod>` (once external mode is added) — record p95 vs Phase 0 baseline.
- [ ] Watch worker process during load — single uvicorn worker should handle 5+ concurrent streams without serialisation.

## C. Real Pinecone retrieval correctness
- [ ] `GET /references?query=patience&sect=shia` — returns relevant Shia hadith with proper metadata.
- [ ] Agentic query *"What did Imam Ali say about justice?"* — references show actual Imam Ali quotes, not random hits (verifies async retrieval doesn't break ranking).
- [ ] Quran-leaning query *"What does Surah Al-Asr teach?"* — `quran_references` SSE event fires with tafsir docs.

## D. Real Redis session persistence
- [ ] First message in a session: *"Tell me about Imam Hussain"*. Second message: *"What happened to him?"* — second response references Hussain (proves history loaded from Redis).
- [ ] Restart the server — same `session_id` second message still has context (proves Redis persistence, not in-memory ephemeral).
- [ ] `redis-cli KEYS "${REDIS_KEY_PREFIX}:*"` shows the session keys with TTL.

## E. Real Postgres (chat persistence + memory)
- [ ] `GET /chats/sessions` (authenticated) — returns list of saved sessions with first-query titles.
- [ ] `GET /chats/sessions/{id}` — full message history matches what was streamed.
- [ ] After Phase 6: kill DB during a request — request errors cleanly, doesn't hang the worker.
- [ ] `SELECT count(*) FROM chat_messages WHERE created_at > now() - interval '1 hour'` matches expected message count.

## F. Fiqh path (Phase 5 / DEE-44 specifically)
- [ ] Fiqh query: *"Is shrimp halal in Twelver Shia fiqh?"* — `fiqh_classification` SSE event fires, `fiqh_decompose`/`fiqh_retrieve`/`fiqh_filter`/`fiqh_assess` status events stream in order, final answer cites Sistani sources, includes fatwa disclaimer.
- [ ] Insufficient-evidence fiqh query (intentionally obscure) — refusal message + `INSUFFICIENT_WARNING` + `FATWA_DISCLAIMER` appear, no hallucination.
- [ ] Unethical query *"How do I hurt someone?"* — early-exit message, no fiqh ruling generated.
- [ ] Concurrent fiqh + non-fiqh queries — neither blocks the other (fiqh runs in `asyncio.to_thread` until Phase 5 lands native async, then runs natively).

## G. Translation + non-English flows
- [ ] Arabic query *"ما رأي الإسلام في الصبر؟"* — `translate_to_english_tool` status event fires, response is in English (or `target_language` if specified).
- [ ] Set `target_language: "arabic"` in request — verify the response language behavior (note: Phase 5+ may still defer reverse translation per existing TODO).

## H. Error paths and resilience
- [ ] Pull the Anthropic API key, send a request — error SSE event fires, doesn't hang.
- [ ] Pinecone unreachable — fallback message *"I couldn't access enough source material..."* is emitted via SSE.
- [ ] Redis unreachable — server still responds (falls back to `EphemeralHistory`); subsequent requests don't have history (acceptable degradation).
- [ ] Malformed request body — 400, no 500.
- [ ] Cancel a stream mid-way (close `curl` connection) — server logs cleanly, no zombie tasks (`lsof` on the process).

## I. Sentry / observability
- [ ] Force an error inside a tool (e.g. corrupt the Pinecone index name in env) — Sentry captures the exception with `correlation_id` matching the SSE response's request.
- [ ] Open the Sentry transaction for a normal request — child spans for `agent`, `tools`, `generate_response` show non-overlapping work for concurrent requests (proves contextvars propagate through `asyncio.to_thread` and async nodes).
- [ ] Logs show `correlation_id` consistently across all log lines for one request.
- [ ] No "scope leak" — concurrent requests' Sentry tags don't bleed into each other.

## J. Auth / boundary
- [ ] Authenticated `/chat/stream/agentic` with valid Cognito JWT — `user_id` appears in logs and Sentry tags, session is namespaced under user.
- [ ] Missing/expired JWT on a route requiring it — 401, no 500.
- [ ] Two different users hitting the same `session_id` — keys are properly namespaced (`{user_id}:{session_id}`), no cross-user leakage in Redis or DB.

## K. Endpoint smoke tests
- [ ] `POST /onboarding` + `GET /onboarding/me` — round-trip works.
- [ ] `GET /primers?lesson_id=...` — returns a primer (or generates one); subsequent calls hit cache.
- [ ] `POST /hikmah/elaborate` — streams elaboration tokens, includes hadith references (Phase 5 makes this fully async).
- [ ] `POST /feedback` — accepted, persisted.
- [ ] `GET /admin/memory` — admin dashboard renders.

## L. Deployment / infra
- [ ] `docker compose build --no-cache && docker compose up -d` — starts cleanly.
- [ ] `alembic upgrade head` — applies any new migrations.
- [ ] Inside container: `python scripts/loadtest_agentic.py --n 10` — concurrency numbers match dev-machine numbers (rules out Docker IO weirdness).
- [ ] Health check (`/_routes` debug endpoint) — all routes registered.
- [ ] Caddy reverse proxy — SSE works through Caddy (no buffering).

## M. Rollback dry-run (per-phase)
- [ ] If you need to revert a single phase: `git revert <merge-commit>` and verify the suite still passes — each phase was designed to be independently rollback-safe.

---

## Acceptance criteria for closing DEE-36

1. Every checklist item above is checked off (or has a tracking issue if deferred).
2. `pytest tests -q` is green on `main`.
3. `documentation/async_baseline.md` shows ≥3× wall-clock improvement at N=10 vs the Phase 0 entry.
4. Sentry transactions for concurrent requests show non-overlapping per-request spans (no scope stacking).
