# LLM Input-Token Cost Reduction — deen-backend

## Context

Production traffic (~10k downloads, ~4,500 questions/week via `POST /chat/stream/agentic`) is generating an Anthropic bill where **80-90% of cost is input tokens on `claude-sonnet-4-6` (LARGE_LLM)**; Haiku spend is negligible because it is used in exactly one place (query enhancer). Deep code analysis (3 exploration passes + verified line-by-line) found the dominant drivers are *structural waste*, not answer length:

1. **Retrieval documents are re-sent to Sonnet 3-4× per request, uncapped.** ToolMessages carry full `page_content_en` + full Arabic `page_content_ar` (never used by any prompt) + **base64-gzip duplicates of the same text** inside raw Pinecone metadata (`metadata.text_ar`/`text_en`/`text_chunk`/`english_quran_translation`). LangGraph's ToolNode serializes with `json.dumps` default `ensure_ascii=True`, so Arabic inflates to **6 ASCII chars per char**. A single hadith doc ≈ 3-6k tokens in the ToolMessage; ~10 docs re-sent on every agent iteration. The generation step *never reads messages* — it reads `state["retrieved_docs"]` — so this payload buys nothing.
2. **Up to 30 messages of verbatim chat history are re-sent 3-5× per request** (intent classifier last-6, every agent iteration, enhancer, generation).
3. **The 6,643-char generation system prompt is structurally uncacheable** — `{references}` and `{target_language}` are interpolated *inside* the `SystemMessage` string ([core/prompt_templates.py:78-85](core/prompt_templates.py#L78-L85)).
4. **The agent loop breaks its own prompt cache**: the system prompt is only inserted on iteration 1 ([agents/core/chat_agent.py:211-215](agents/core/chat_agent.py#L211-L215)); iteration ≥2 sends *no system message*, so the cached tools+system prefix can't extend, and no messages-tier cache breakpoint exists.
5. **Fiqh streaming requests generate the full answer TWICE** — `_generate_fiqh_response_node` has no `streaming_mode` guard (its docstring claims a bypass that doesn't exist), then `pipeline_langgraph.py:412-418` streams the same generation again. Fiqh decompose also runs twice per iteration.
6. Every request pays **2 Sonnet calls before anything else** (intent + fiqh classification — both on LARGE_LLM despite docstrings claiming "small LLM").

**Estimated per-request Sonnet input today: ~49k tokens (typical non-fiqh) / ~29k (fiqh single-iteration incl. duplicated generation)** ≈ 207M input tok/wk ≈ **~$620/wk input**. Target after this plan: **≈50-65% reduction** (billed-equivalent ~13-19k tok/request) with no grounding/citation quality loss.

### User decisions (locked)
- **No Sonnet→Haiku downgrades in this initiative** (analysis confirms model mix is only ~4-6% of savings — not the leak). Documented as follow-up.
- **History: per-call read-side budgets now; conversation summarization added as a final enhancement phase** (long chats get a summary so UX doesn't degrade).
- **Bench treats fiqh and general pipelines as separate slices** (different pipelines → separate baselines, gates, and reports).
- **Linear: one single detailed issue** (content in §Linear below). Linear MCP is unauthenticated in the planning session — creating the issue is execution step 1 (requires `/mcp` OAuth once, or paste the content manually).
- Pricing facts used: Sonnet 4.6 $3/$15 per MTok, cache read 0.1×, cache write 1.25× (5-min TTL); Sonnet min cacheable prefix 1024 tok (repo comment saying 2048 at [core/chat_models.py:16](core/chat_models.py#L16) is stale); max 4 `cache_control` breakpoints/request; prefix order tools→system→messages.

### Process notes
- Repo mandates GSD workflow for edits: start each phase via `/gsd:execute-phase` (or `/gsd:quick` for the small fixes) where available.
- All phases keep these suites green: `tests/test_agentic_streaming_sse.py`, `tests/test_sse_event_order_snapshot.py` (syrupy SSE contract), `tests/test_fiqh_*.py`, `tests/test_cache_metrics_breadcrumb.py`, `tests/test_async_concurrency_full.py`, `agent_tests/test_prompt_cache.py`.
- Commit this plan into the repo as `documentation/token_cost_reduction_plan.md` in Phase 0 so the Linear issue can link it.

---

## Phase 0 — Instrumentation & baseline bench (prerequisite; no behavior change)

**Goal:** measure before optimizing; every later phase gates on this bench.

1. **New `core/token_telemetry.py`**
   - `record_llm_usage(site: str, response)` reading **raw** `response.response_metadata["usage"]` (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`). Never LangChain's `usage_metadata` wrapper (streaming double-count bug, GitHub #32818 — already documented at [chat_agent.py:219-221](agents/core/chat_agent.py#L219-L221)).
   - For streamed calls ([pipeline_langgraph.py:418](core/pipeline_langgraph.py#L418), [:486](core/pipeline_langgraph.py#L486)): merge usage across chunks taking **max per field** (input/cache arrive on message_start, output on message_delta) — never sum.
   - Per-request accumulator via `contextvars.ContextVar` (`token_usage_by_site`), set/reset in `response_generator()` alongside the existing `fiqh_status_queue` ([pipeline_langgraph.py:184-185](core/pipeline_langgraph.py#L184-L185)). Must no-op safely when usage is absent (test fakes emit none).
2. **Instrument every call site** (one line each): agent iterations ([chat_agent.py:218](agents/core/chat_agent.py#L218) — keep existing cache-metrics code), early-exit writers (:349/:369/:391), `_generate_response_node` (:322), fiqh response node (:489), intent classifier ([modules/classification/classifier.py:87,102](modules/classification/classifier.py)), fiqh classifier ([modules/fiqh/classifier.py:96](modules/fiqh/classifier.py#L96)), enhancer ([modules/enhancement/enhancer.py:48](modules/enhancement/enhancer.py#L48)), translator, all fiqh nodes (decomposer/filter/sea/refiner/generator), both streamed generations ([pipeline_langgraph.py:417-422](core/pipeline_langgraph.py#L417-L422), [:485-491](core/pipeline_langgraph.py#L485-L491)).
3. **Extend the Sentry breadcrumb** — `_emit_cache_metrics_breadcrumb` ([pipeline_langgraph.py:110-143](core/pipeline_langgraph.py#L110-L143)) gains `input_tokens_total`, `output_tokens_total`, per-site map (additive kwargs on [core/sentry.py:103](core/sentry.py#L103)). Update `tests/test_cache_metrics_breadcrumb.py` shape test deliberately in the same PR if needed.
4. **New `scripts/token_bench.py`** — drives a live local server (`uvicorn` + dev `.env`, real Anthropic+Pinecone) over the golden set; reuses the SSE drain from [tests/test_real_llm_perf.py:49-67](tests/test_real_llm_perf.py#L49-L67); per-site usage read via an env-gated (`TOKEN_BENCH_DEBUG=1`) `usage` SSE event emitted just before `done` from the accumulator (off by default → syrupy snapshot untouched). Emits per-stage markdown table (calls, in, out, cache_read, cache_write, $) + JSON snapshot appended to **new `documentation/token_baseline.md`** with `--label`, mirroring `scripts/loadtest_agentic.py` → `documentation/async_baseline.md` conventions (regex-parseable for a future ratchet test). **Fiqh and non-fiqh reported as separate slices.**
5. **Golden set** — new `tests/golden_queries.py` (data module), ~32 entries, per user decision: existing test-suite queries + synthesized multi-turn conversations on the same topics:
   - 8 non-fiqh single-turn (patience, Imam Ali, Imamate, tawhid + Karbala, Nahjul Balaghah, Quran-theme, seeking knowledge)
   - 6 multi-turn scripted conversations (e.g. "Who was Imam Ali?" → "What did he say about justice?" → "Which book is that from?") — exercises history budgets + multi-turn caching
   - 6 fiqh single-iteration (wudu/ghusl/khums/salah conditions) + 3 fiqh multi-iteration (compound questions known to trigger refine)
   - 3 UNETHICAL-adjacent adversarial (routing must hold), 3 off-topic early-exit, 2 casual, 1 non-English (Urdu/Arabic)
6. **Quality eval harness** (in the bench): deterministic grounding checks (every citation in the answer must exist in the emitted `hadith_references`/`quran_references` SSE payloads; fiqh answers must keep `## Sources` + disclaimer per [modules/fiqh/generator.py](modules/fiqh/generator.py) contract); Sonnet LLM-judge on blind A/B pairs (groundedness, citation completeness, Twelver-Shia fidelity, usefulness, 1-5 each); behavioral diffs (tool-call sequence, iteration count, doc counts, labels); human spot-check 8/32 before merging risky phases.
7. **Baseline runs**: capture baseline snapshot; validate cost model against ≥1 full day of Anthropic Console usage (input/output/cache-read/cache-write per model); target ±15% agreement before trusting gate deltas.
8. Optional CI wrapper `tests/test_token_bench.py -m real_llm` (excluded by default via `pytest.ini` addopts).

**Gate:** complete per-site table produced; console reconciliation ±15%.

---

## Phase 1 — Zero-waste fixes (no retrieval/semantic behavior change)

1. **Fiqh double-generation guard** *(bug fix — immediate ~5.5k in + ~1k out tokens saved per fiqh request)*: first line of `_generate_fiqh_response_node` ([chat_agent.py:458-505](agents/core/chat_agent.py#L458-L505)): `if state.get("streaming_mode"): return {}` (mirrors the non-fiqh guard at :526-537). Fix the false docstring at :462-464. Non-streaming `/chat/agentic` unaffected.
2. **Drop `check_if_non_islamic_tool` from the bound set** ([chat_agent.py:59-66](agents/core/chat_agent.py#L59-L66), [:83-91](agents/core/chat_agent.py#L83-L91)) — intent classification already runs deterministically on every request before the agent; the tool is triple duty (saves 1,266 chars/agent-call + removes duplicate Sonnet call path). Keep the handler at :272-276 (harmless). Remove status message ([pipeline_langgraph.py:84](core/pipeline_langgraph.py#L84)); update `AGENT_SYSTEM_PROMPT` accordingly. Note: changes tool bytes → one-time full cache invalidation at deploy (bundle with item 5/6).
3. **Bound `num_documents`**: clamp inside tool bodies ([agents/tools/retrieval_tools.py:19](agents/tools/retrieval_tools.py#L19), :76, :202 — shia 1-10, sunni 0-5, quran 0-5) and in `_apply_tool_call_defaults` ([chat_agent.py:608-616](agents/core/chat_agent.py#L608-L616)).
4. **`max_iterations` default 5 → 3** ([agents/config/agent_config.py:109-114](agents/config/agent_config.py#L109-L114)), bound `le=10`.
5. **Trim `AGENT_SYSTEM_PROMPT`** ([agents/prompts/agent_prompts.py:5-143](agents/prompts/agent_prompts.py#L5-L143), 7,086 → ≤3,500 chars): delete Voice & Personality block (agent never writes user-facing text — generator owns voice), delete Step-1 classification section (after item 2), compress 3 worked examples → 1. **Keep** retrieval-strategy + query-construction rules verbatim (quality-load-bearing).
6. **Trim tool docstrings** ([retrieval_tools.py:20-51](agents/tools/retrieval_tools.py#L20-L51), :77-113, :203-239; 6,673 → ~2,500 chars): keep when-to-use rules + arg meanings; drop return-shape prose and doc-count essays.
7. **Trim `generatorSystemTemplate`** ([core/prompt_templates.py:8-66](core/prompt_templates.py#L8-L66) → ~4,500 chars): consolidate 4 duplicate citation-format instructions, collapse 3 examples → 1 hadith + 1 tafsir. **Keep all anti-hallucination clauses verbatim.**
8. Hygiene: fix `api/chat.py:149-153` docstring (`gpt-4o`, `max_iterations: 15` examples); delete dead config fields ([agent_config.py:33-50](agents/config/agent_config.py#L33-L50), :116-134) after re-grep for readers; fix stale comments ([chat_models.py:16](core/chat_models.py#L16) cache minimum; [config.py:26](core/config.py#L26) TTL comment — also flag to ops that `.env` `REDIS_TTL_SECONDS=1440` is 24 *minutes*, not hours: product decision, not code).

**New tests:** clamp test; `streaming_mode=True` → fiqh node makes zero LLM calls. Check `tests/test_fiqh_integration.py:131-196` (patches `get_generator_model`) — adjust to the streamed call if it drove the old node.
**Gate:** bench shows no grounding/citation regression; tool-selection distribution unchanged within noise; expected token drops confirmed.

---

## Phase 2 — Payload diet (largest absolute win; ~35-45% of Sonnet input spend)

1. **Metadata whitelist at the source** (kills base64 blobs):
   - [modules/reranking/reranker.py:129-137](modules/reranking/reranker.py#L129-L137) (+ dense-merge dict ~:42-108): build `metadata` as whitelist copy — the 15 scalar fields consumed by [core/utils.py:78-92](core/utils.py#L78-L92) (`author, volume, book_number, book_title, chapter_number, chapter_title, collection, grade_ar, grade_en, hadith_id, hadith_no, hadith_url, lang, sect, reference`) — explicitly dropping compressed `text_en`/`text_ar`.
   - [modules/retrieval/retriever.py:113-121](modules/retrieval/retriever.py#L113-L121), :212-221: same for Quran docs (drop `text_chunk`, `english_quran_translation`; keep `surah_name, title, chapter_number, verses_covered, author, collection, volume, sect`).
   - **Keep `page_content_ar` as a top-level doc field** — the frontend reference JSON needs it ([core/utils.py:260](core/utils.py#L260)); it just never enters LLM payloads (item 2 handles that).
   - Before finalizing: grep `metadata.get(`/`metadata[` in `core/utils.py` + `services/` (incl. reference translation service) and extend whitelist as needed. Add a **byte-identical regression test** on the frontend reference JSON for canned docs.
2. **Compact ToolMessage rewrite** (flag `TOOLMSG_COMPACT=1`): in `_tool_node`, between `_record_retrieval_result` ([chat_agent.py:301](agents/core/chat_agent.py#L301)) and `state["messages"].extend` (:303-304), replace retrieval ToolMessage `content` with `json.dumps({source, count, query_used, error, documents:[compact]}, ensure_ascii=False)` where compact doc = `{hadith_id|chunk_id, book_title, chapter_title, hadith_no|verses_covered, sect, snippet: page_content_en[:300]}`. Full docs still flow to `state["retrieved_docs"]` (verified: state is populated by parsing the tool payload *before* messages are appended — generation is untouched). Snippet length is a bench tunable (150/300/600).
3. **Slim `compact_format_references`** ([core/utils.py:97-117](core/utils.py#L97-L117), :134-150): hadith scaffold → citation-critical lines only (Book Title, Author, Volume, Book#, Chapter#+Title, Hadith#, Reference, Grade EN, Sect — drop URL/Language/Hadith ID/Grade AR); shorten dash separators to `---`; cap Quran `translation+tafsir` combined at ~2,200 chars (today up to 4,500).
4. **History budgets** (flag `HISTORY_BUDGETS=1`): new `core/history_budget.py` → `budget_messages(messages, max_msgs, max_chars)` (most-recent-first, never split a message, keep user/assistant pairs). Apply: generation last 10 / ~8,000 chars ([pipeline_langgraph.py:477-483](core/pipeline_langgraph.py#L477-L483)); agent initial history last 10 (at `create_initial_state` call sites, [chat_agent.py:790-798](agents/core/chat_agent.py#L790-L798)); enhancer last 6 ([enhancer.py:58](modules/enhancement/enhancer.py#L58)); classifier context 6 → 4 ([modules/context/context.py:3](modules/context/context.py#L3)). Redis keeps storing 30 — read-side only.

**Gate:** grounding/citation rubric unchanged (both slices); agent iteration count + tool-mix within ±1 call of baseline; measured iteration-2 input tokens down ≥60%; frontend reference JSON byte-identical.

---

## Phase 3 — Caching architecture (converts remaining repeats to 0.1× reads)

Breakpoint budget (max 4): tools (exists, [retrieval_tools.py:277-281](agents/tools/retrieval_tools.py#L277-L281)) + system (exists) + rolling messages breakpoint (new) + 1 spare.

1. **Generator prompt split** (cross-request shared prefix): restructure `generatorSystemTemplate` so all static text precedes interpolations, then `generator_messages` ([prompt_templates.py:70-85](core/prompt_templates.py#L70-L85)) builds `SystemMessage(content=[{static block + cache_control}, {dynamic: target_language + references}])`. Static ≈1,700+ tok > 1024 min → cached across **all** users (~27 req/hr keeps 5-min TTL warm). Both call sites unchanged in signature ([chat_agent.py:312-316](agents/core/chat_agent.py#L312-L316), [pipeline_langgraph.py:478-483](core/pipeline_langgraph.py#L478-L483)).
2. **System prompt on every agent iteration** ([chat_agent.py:211-215](agents/core/chat_agent.py#L211-L215)): insert `make_cached_system_message(AGENT_SYSTEM_PROMPT)` every iteration, not just `iterations == 1` — restores identical tools+system prefix on iter ≥2 (today iter-2 requests have *no system at all*).
3. **Append-only messages**: persist the initial HumanMessage and each iteration summary into `state["messages"]` (instead of local-only) so iteration N+1's request = iteration N's request + [AI, ToolMessages, new summary] — an exact prefix extension. (Flag `AGENT_CACHE_V2=1` guards 2-4.)
4. **Rolling messages breakpoint**: `cache_control` on the newest appended HumanMessage (content-block form); sweep the marker off previously persisted messages before each request so ≤4 breakpoints total. Per-iteration adds (~1 AI + ≤3 tool + 1 human) stay within the 20-block lookback.
5. **Multi-turn cross-request reuse** comes free from 2-4 (Redis history loads verbatim; follow-up within TTL reads the whole prefix at 0.1×). Keep 5-min TTL; evaluate 1h (2× write) only if Phase 0 telemetry shows session-return patterns justify it.
6. **Telemetry**: include generator-call cache fields in the breadcrumb (drop the "generator excluded by design" carve-out at [pipeline_langgraph.py:123-127](core/pipeline_langgraph.py#L123-L127)); bench asserts iter≥2 cache-read ratio ≥0.7.

**Cache-key stability (verified):** tools/system derive from module-level constants; per-request `ChatAnthropic` construction injects no per-request bytes; conftest stubs monkeypatch `chat_agent_mod.ChatAnthropic` — keep that module attribute name.
**New tests:** prefix-extension unit test (iteration N+1 rendered list extends N); ≤4 markers per request; cache-read ratio assertion in bench.
**Gate:** billed-equivalent input (in + 1.25×write + 0.1×read) down ≥15% vs post-Phase-2; answer rubric unchanged; expected one-time write spike at deploy then read-ratio ≥0.6 within an hour.

---

## Phase 4 — Fiqh subsystem structural fixes

1. **Remove double decompose**: `aretrieve_fiqh_documents` ([modules/fiqh/retriever.py:216-236](modules/fiqh/retriever.py#L216-L236)) gains `sub_queries: list[str] | None`; when provided, skip internal `adecompose_query` (:222). `_retrieve_node` ([agents/fiqh/fiqh_graph.py:56-106](agents/fiqh/fiqh_graph.py#L56-L106)) passes decompose output on iter 1 and refinement queries on iter ≥2 (today it forwards only `prior_queries[-1]` and re-decomposes — wasteful *and* lossy). Flag `FIQH_V2_RETRIEVAL=1`.
2. **Flatten retry stacking**: `ChatAnthropic max_retries` 5 → 2 ([chat_models.py:32](core/chat_models.py#L32), [chat_agent.py:78](agents/core/chat_agent.py#L78)); `@anthropic_retry` attempts 3 → 2 ([core/resilience.py:89](core/resilience.py#L89)). Worst case 18 → 6 billed attempts under 429/529.
3. **Evidence caps**: hard cap 30 docs entering `_filter_node`; top-K(20) by RRF into filter/SEA formatting ([fiqh_graph.py:109-183](agents/fiqh/fiqh_graph.py#L109-L183)).

**New tests:** `adecompose_query` called exactly once per fiqh request (2-iteration mock).
**Gate:** fiqh slice — SEA verdict distribution + citation accuracy unchanged; fiqh Sonnet calls/request ~8 → ~5-6.

---

## Phase 5 — Conversation summarization (UX enhancement, user-requested)

When a session exceeds the per-call history budget (e.g. >10 messages), maintain a running summary so long conversations keep context without paying verbatim-history prices:

1. New summarization step in `services/chat_persistence_service.py` after `aappend_turn_to_runtime_history` (:266-281): when message count crosses the threshold, generate/refresh a compact "conversation so far" summary (major topics, user's stated context, open threads; ~600-1,000 chars) and store beside history (new Redis key `{prefix}:{session_id}:summary`). Use **SMALL_LLM (Haiku)** — a *new* auxiliary call, not a downgrade (consistent with the enhancer precedent); confirm at review.
2. `budget_messages` callers prepend the summary (as a system-adjacent context block *after* the cached static prefix, before recent messages) when a summary exists.
3. Run summarization async post-response (fire-and-forget task) so it never adds user-facing latency.

**Gate:** multi-turn golden slice — follow-up answer quality ≥ budgets-only baseline; no added TTFB.

---

## Deferred follow-ups (documented, out of scope)
- **Sonnet→Haiku reallocation** of classifiers/translator/fiqh-utility calls (~4-6% further savings; per-site env pins design ready; requires adversarial UNETHICAL gate at 100%).
- Merged intent+fiqh classifier (one structured-output call).
- Generation-as-final-agent-turn (docs paid ~once at 0.1×; large SSE blast radius).
- Output-length trimming / `max_tokens` 4096→2048 for generation (output is only ~10-20% of cost).

## Key risks
| Risk | Mitigation |
|---|---|
| ToolMessage slimming changes agent "enough evidence" judgment (over/under-retrieval) | Snippet length tunable; `_build_iteration_summary` already carries counts/coverage (strengthen with titles if drift); gate on tool-sequence + iteration-count diffs, not just answer rubric |
| Metadata whitelist breaks frontend refs/translation service | Byte-identical reference-JSON regression test; grep consumers before finalizing; additive-safe |
| History budgets drop the turn a follow-up refers to | Generous recency windows; enhancer resolves references; multi-turn slice gates; Phase 5 summary; `HISTORY_BUDGETS` flag revert |
| Append-only messages × `add_messages` reducer duplication/reordering | Mirrors existing `.append(response)` pattern (:234); prefix-extension unit test; marker sweep before request build |
| Cross-request cache assumes byte-identical prefixes forever | Cache-read-ratio telemetry + alert; invariant documented atop `agent_prompts.py` |
| Deploy-time cache invalidation (tool/prompt byte changes) | Bundle all byte-changing edits per release; expect one-time 1.25× write spike |
| Test-stub coupling (`ChatAnthropic` patch, factory names) | Preserve names; update enumerated patch sites in same PR |

## Verification (every phase)
1. `pytest tests -q` green (stub suites, SSE snapshot, fiqh units, cache breadcrumb, concurrency gates).
2. `python scripts/token_bench.py --label phase-N` against live local server (dev `.env`) → per-site token table + JSON snapshot in `documentation/token_baseline.md`; compare vs previous label; **fiqh + non-fiqh slices separately**.
3. Quality gates: deterministic grounding checks pass; LLM-judge A/B no regression; human spot-check (8/32) for Phases 2-4.
4. After Phase 2 and Phase 3: one-day Anthropic Console reconciliation (±15%) — these carry the biggest modelled claims.
5. Prod rollout per phase behind its flag; watch Sentry breadcrumb (`cache_efficiency_ratio`, new token totals) for 24-48h; rollback = flag off.

## Linear (execution step 1)
Create **one issue** (team DEE) titled **"Reduce Sonnet input-token cost ~50-65% on /chat/stream/agentic (instrumentation, payload diet, prompt caching, fiqh fixes)"** containing: the Context summary above (findings 1-6 + cost table), the six phases as checklists with file anchors, gates per phase, the deferred-follow-ups list, and a link to `documentation/token_cost_reduction_plan.md` (this plan, committed in Phase 0). Priority: High. Labels: cost, backend. Blocked note: Linear MCP needs one-time `/mcp` OAuth in an interactive session; otherwise the issue body is paste-ready from this plan.
