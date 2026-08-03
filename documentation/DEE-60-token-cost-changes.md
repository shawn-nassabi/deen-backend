# DEE-60: Token-Cost Reduction — What Changed and Why

*Team summary — August 2026 · PR [#109](https://github.com/shawn-nassabi/deen-backend/pull/109) · Linear [DEE-60](https://linear.app/deen-team/issue/DEE-60) · detailed plan: `documentation/token_cost_reduction_plan.md` · raw bench data: `documentation/token_baseline.md`*

---

## TL;DR

~80-90% of our Anthropic bill was **input tokens on Sonnet**. We instrumented every LLM call, measured where the tokens actually went, and removed the waste in five gated phases. Answer quality was blind-judged at every step and **ended better than it started**.

| | Before | After | Change |
|---|---:|---:|---:|
| Cost per typical (non-fiqh) answer | $0.210 | **$0.092** | **−56%** |
| Raw input tokens per answer | ~50,200 | **~8,700** | **−83%** |
| Agent-planner full-price tokens (24-question bench run) | 947,000 | **192** | ~eliminated |
| Projected weekly input spend @ 4,500 questions | ~$760 | **~$360** | **−53% ≈ $1,700/month** |
| Answer quality (blind judge, 4 axes, 1-5) | 4.04 / 3.79 / 4.58 / 4.50 | **4.08 / 4.12 / 4.79 / 4.83** | equal or better on every axis |

*(Judge axes: groundedness / citation completeness / Twelver-Shia fidelity / usefulness. Fiqh answers cost roughly the same as before by deliberate design — see "What we protected".)*

---

## Where the money was actually going

Live measurement (Phase 0) confirmed six drivers. In plain terms:

1. **We paid for the same documents 3-4 times per question.** Retrieved hadith went to the planning model as raw JSON — including the full Arabic text (which no prompt ever used) *and* compressed base64 copies of the same text hiding inside Pinecone metadata — and were re-sent on every planning iteration. The answer-writing step never even reads that copy; it uses its own.
2. **We re-sent up to 30 messages of chat history 3-5 times per question** (classifier, every planner iteration, query enhancer, answer generation).
3. **The answer-writer's instructions could never be cached** — the retrieved references were pasted *inside* the system prompt, making it unique every time.
4. **The planner broke its own cache** — its system prompt was only sent on the first iteration, so Anthropic's prefix cache couldn't extend across iterations, and there was no cache marker on the conversation.
5. **The fiqh pipeline decomposed every query 2-4 times** — and threw away most of the sub-queries it generated.
6. **Every request paid two full Sonnet classifier calls before doing anything** — and the agent sometimes ran a *third*, redundant classification via a tool.

Plus two things nobody knew were broken (found by the measurement, fixed in Phase 1):

- **Fiqh answers never actually streamed.** A state-handling bug made the streaming branch unreachable: users stared at "Preparing fiqh answer..." for 10-15 s, then the whole answer appeared as one blob — and the `fiqh_references` cards **never reached the app at all**.
- Under API overload, one logical LLM call could legally retry **up to 18 billed times**.

---

## What changed, phase by phase

Each phase is one commit, has an env-var kill-switch (all default **on**; set `=0` to revert without a deploy), and was gated on a 32-question live bench + a blind A/B quality judge before landing.

### Phase 0 — Measure first (`4d434f1`)

**Design decision:** no optimization without per-call-site numbers. Every one of the ~15 LLM call sites now records raw Anthropic usage (input / output / cache-read / cache-write) into a per-request accumulator; totals ride the existing Sentry `cache_metrics` breadcrumb, and a debug-only `usage` SSE event (behind `TOKEN_BENCH_DEBUG=1`, never on in prod) feeds the bench.

**Tooling you can use anytime:**

```bash
# start the server with the debug usage event:
TOKEN_BENCH_DEBUG=1 uvicorn main:app --port 8000
# run the 32-question golden set and record a labeled snapshot:
python scripts/token_bench.py --label my-experiment
# blind A/B quality judge between any two recorded runs:
python scripts/token_bench.py --judge phase-4 my-experiment
```

The golden set (`tests/golden_queries.py`) covers general theology, multi-turn conversations, fiqh (single and multi-iteration), off-topic/casual routing, UNETHICAL-adjacent probes, and Urdu — with fiqh and general always reported as **separate slices** because they are different pipelines.

### Phase 1 — Stop obvious waste + fix fiqh streaming (`fc678f8`, `f2516ae`)

- **Fiqh streaming restored**: the pipeline now merges LangGraph node updates instead of keeping only the last one, and the graph's duplicate generation node is skipped on the streaming path. Fiqh answers now stream token-by-token and `fiqh_references` events reach the app — for the first time in production. Cost-neutral (still exactly one generation per request).
- **Removed the redundant classifier tool** the agent occasionally called (classification already runs deterministically before the agent): intent classification is now exactly one call per request.
- **Bounded what the model can ask for**: retrieval sizes clamped (Shia ≤10, Sunni ≤5, Quran ≤5 docs), planner iterations capped at 3 (was 5, docs advertised 15).
- **Trimmed the three big prompts** (planner 7,086 → ~3,050 chars; tool descriptions ~6,700 → ~2,100; answer-writer 6,643 → ~3,950) — every anti-hallucination and citation rule kept verbatim; only redundancy, dead examples, and a voice section the *planner* never needed (voice lives with the answer-writer) were cut. A follow-up commit restored "always end with 2-3 suggested follow-up questions" as its own numbered objective after the bench caught weakened compliance.

### Phase 2 — The payload diet (`001c48a`) — the biggest lever · kill-switches `TOOLMSG_COMPACT`, `HISTORY_BUDGETS`

**Design decision:** the planner and the answer-writer need *different* views of the evidence, so stop sending both of them everything.

*Flow, before → after (example: "What does Islam say about patience?"):*

- **Before:** each retrieved hadith entered the planner's transcript as ~3-6k tokens of JSON — full English text, full Arabic text, plus base64-gzip duplicates of both from raw Pinecone metadata (Arabic inflated ~6× by ASCII escaping) — and was re-sent on every subsequent iteration.
- **After:** retrieval still stores **full documents in state** (that's what the answer-writer and the app's reference cards consume), but the planner's transcript gets a compact card per document:

```json
{"id": "h-2041", "title": "Al-Kafi", "chapter": "Patience", "number": "10",
 "sect": "shia", "snippet": "Indeed, patience is half of faith. ..."}
```

- **Metadata whitelists at the retrieval boundary**: only the 15 hadith / 11 Quran fields that formatters and the app actually read survive; the compressed blobs never leave the retrieval module. A byte-identical regression test proves the app-facing reference JSON (including `text_ar`) is unchanged.
- **Reference block for the answer-writer slimmed**: citation-critical lines only (dropped internal Hadith ID, URL, language tag, Arabic grade — all still in the app's reference cards), Quran verse+tafsir capped at ~2,200 chars/doc.
- **History budgets (read-side only)**: each call site now sends a tailored window — planner and answer-writer get the last 10 messages (~8k chars), enhancer 6, classifier 4. Redis still stores the full 30; nothing is deleted.

**Result:** general slice $0.210 → **$0.095/turn (−55%)**; planner input −88%; and the follow-up-question canary that *failed* at baseline ("Which book is that saying from?" used to come back empty-handed) started passing — the leaner history actually improved follow-up handling.

### Phase 3 — Make Anthropic's cache work for us (`63e278d`) · kill-switch `AGENT_CACHE_V2`

**Design decision:** Anthropic prompt caching is a byte-prefix match, so build every request as an *extension* of the previous one.

- The planner now sends its (byte-identical) system prompt on **every** iteration and appends its per-iteration notes into state, so iteration N+1's request literally begins with iteration N's request. A rolling `cache_control` marker rides the newest message (older markers swept; ≤4 breakpoints total: tools + system + newest message).
- The answer-writer's prompt was restructured: the instruction block is now static and byte-identical across all requests; the target language, references, and question moved to the final user message; a cache marker rides the conversation history — so a follow-up turn re-reads the previous turn's prefix at 10% price.

**Result:** planner full-price input collapsed from 116k (post-diet) to **189 tokens** across the whole general bench — everything else became cache reads (0.1×) and writes (1.25×), with a 68.5% read ratio even on a bench of mostly fresh sessions (production sessions re-use far more). The answer-writer recorded its first-ever cache reads on follow-up turns.

### Phase 4 — Fiqh structural fixes (`54824ae`) · kill-switch `FIQH_V2_RETRIEVAL`

**Design decision (per the FAIR-RAG constraints in DEE-60):** on the fiqh route, reduce tokens only at the retrieval/orchestration level — never touch evidence text, the SEA gate, the filter, or the iteration loop.

- **One decomposition per query.** Before: the graph decomposed the question into up to 4 keyword-rich sub-queries, forwarded only the *last* one, and the retriever **re-decomposed it** — a duplicate LLM call per iteration that discarded most of the decomposer's work. Now the graph hands its full output to retrieval (`pending_queries`), and *all* sub-queries search concurrently. Bench: decomposer calls **25 → 9** (exactly 1/query).
- **Evidence cap**: at most 30 accumulated docs enter the filter call.
- **Retry stack flattened**: SDK retries 5→2 × outer retries 3→2 ⇒ worst case **6** billed attempts (was 18).

**Result:** the strongest quality verdict of the initiative — the judge preferred Phase 4 answers **14-4-6 with higher means on all four axes** (fuller retrieval coverage = better-grounded answers). Net fiqh cost stayed ~flat by design: the saved calls were reinvested in richer evidence.

### Phase 5 — Long-chat summaries (`7307fc1`) · kill-switch `HISTORY_SUMMARY`

**Design decision:** history budgets must not cost long conversations their memory.

Once a session passes 10 messages, a background **Haiku** task (fire-and-forget after each turn — zero user-facing latency) maintains a ≤1,000-char summary of the *older* turns in Redis. At prompt-build time, the summary is prepended **only when the budget actually dropped messages**. It refreshes every second turn to limit cache churn.

*Live verification:* in an 8-turn session, turn 1 ("I'm a new convert named Daniel...") had been budget-dropped by turn 8 — the background summary had captured the convert background, name, every topic discussed with its citations, and open threads, and the follow-up produced a context-aware study recommendation.

---

## What we protected (and verified)

- **No fiqh evidence text was ever truncated.** The payload diet applies to the non-fiqh path only; fiqh evidence reaches filter → SEA → generator whole. SEA and the filter are untouched; the 3-iteration loop is intact.
- **Reference cards in the app are unchanged** — including the Arabic text. Live-verified: `hadith_references` still carries all 19 fields with real `text_ar`; `quran_references` all 15 fields; the DEE-67 translation joins still run (`text_translated` is `None` in dev only because the dev `reference_translations` table is empty — the batch job was never run there).
- **Answer formatting contract**: bold-italic quoted references, complete citations (book/volume/chapter/hadith number; surah/verse; tafsir volume), fiqh `## Sources` + fatwa disclaimer, follow-up questions — all audited across bench snapshots and live spot checks.
- **SSE contract**: event types and payload shapes unchanged (syrupy snapshot untouched). The fiqh path *gained* streaming + `fiqh_references` (restoring documented behavior).
- **Every phase blind-judged**: a Sonnet judge scored order-randomized A/B pairs of the same questions at every gate; no phase shipped with a lower groundedness or citation score.

## Numbers per phase (general slice, same 32-question set)

| Phase | $/turn | Uncached input/turn | Judge vs previous |
|---|---:|---:|---|
| 0 — baseline | $0.2102 | 50,247 | — |
| 1 — zero-waste | $0.2056 | 48,927 | ≥ on all axes (12-10-2) |
| 2 — payload diet | $0.0948 | 13,949 | ≥ on all axes (12-8-4) |
| 3 — caching | $0.0917 | 8,748 | citations ↑, rest tied (9-7-7) |
| 4 — fiqh fixes | $0.0919 | 8,708 | **all axes ↑ (14-4-6)** |

*(Bench sessions are mostly fresh; production cache re-use should beat these numbers. List prices: Sonnet $3/MTok in, $15/MTok out; cache read 0.1×, write 1.25×.)*

## Ops cheat-sheet

- **Kill-switches** (env, all default on): `TOOLMSG_COMPACT`, `HISTORY_BUDGETS`, `AGENT_CACHE_V2`, `FIQH_V2_RETRIEVAL`, `HISTORY_SUMMARY` — `=0` reverts that phase live. Caveat from the independent review: the Phase 1 prompt *trims* and the classifier context window are not flag-gated — a full rollback to pre-branch prompts is a commit revert, not a flag flip.
- **First deploy** invalidates the Anthropic prompt cache once (tool/system bytes changed): expect a brief cache-write blip, then it re-warms within minutes.
- **Monitoring**: the Sentry `cache_metrics` breadcrumb now carries `input_tokens_total`, `output_tokens_total`, and a per-site usage map for every turn.
- **Known/pre-existing**: 17 test failures predate this work (machine-timing concurrency gates, one Redis-env fiqh test, primer-service tests); the intent classifier refuses meta-questions about the conversation itself ("what did I tell you earlier?") as non-Islamic — flagged for product discussion.
- **Remaining checklist**: one-day Anthropic Console reconciliation (compare console usage vs bench extrapolation, ±15%).

## Deliberately deferred (documented in the plan)

Sonnet→Haiku for classifier/utility calls (~4-6% more, needs a 100% adversarial-safety gate) · merging the two classifiers into one call · generating the answer inside the agent conversation (docs would be paid ~once at cache price; big SSE blast radius) · shortening answers (output is only ~10-20% of cost).
