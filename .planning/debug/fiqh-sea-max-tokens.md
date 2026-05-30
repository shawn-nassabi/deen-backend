---
status: awaiting_human_verify
trigger: "Fiqh SEA max_tokens causing SEAResult ValidationError — LLM response truncated on iteration 2 (doc_count=21) and iteration 3 (doc_count=30)"
created: 2026-05-25T00:00:00Z
updated: 2026-05-25T00:00:00Z
---

## Current Focus

hypothesis: CONFIRMED — get_classifier_model() in core/chat_models.py sets max_tokens=2048. SEA uses this model via with_structured_output(SEAResult). With 21+ docs of evidence context, the SEAResult structured output (findings with citations, confirmed_facts, gaps, verdict) exceeds 2048 tokens. The LLM response is truncated, LangChain's output parser gets incomplete JSON, and Pydantic validation fails on the missing fields.
test: Verified by reading the code — get_classifier_model() max_tokens=2048, sea.py uses it with structured output
expecting: N/A — root cause confirmed
next_action: Apply fix — create a dedicated get_sea_model() with max_tokens=4096 in core/chat_models.py

reasoning_checkpoint:
  hypothesis: "get_classifier_model() sets max_tokens=2048 which is insufficient for SEAResult structured output when evidence context is large (21+ docs). The LLM hits the token limit, truncates the structured JSON, and LangChain's output parser fails with ValidationError on missing fields."
  confirming_evidence:
    - "core/chat_models.py line 63-69: get_classifier_model() creates ChatAnthropic with max_tokens=2048"
    - "modules/fiqh/sea.py line 105-106: _aassess_evidence_call uses get_classifier_model().with_structured_output(SEAResult)"
    - "Sentry log shows 'Output parser received a max_tokens stop reason' — direct evidence the LLM exhausted its token budget"
    - "Fails on iteration 2 (doc_count=21) and iteration 3 (doc_count=30) but works on iteration 1 (doc_count=5) — confirms it's proportional to evidence size"
    - "SEAResult requires findings (list of Finding with description, confirmed, citation, gap_summary), confirmed_facts (list[str]), gaps (list[str]), and verdict — complex structured output that scales with evidence count"
  falsification_test: "If we set max_tokens=4096 for the SEA model and the error persists, this hypothesis is wrong"
  fix_rationale: "Increasing max_tokens for the SEA-specific model directly addresses the root cause — the LLM needs more output budget to produce the full SEAResult when evidence context is large. 4096 matches get_generator_model() which also handles large evidence contexts."
  blind_spots: "We haven't tested whether 4096 is sufficient for even larger evidence sets (e.g., 50+ docs). However, FAIR-RAG caps at 3 iterations and the filter step constrains doc count, so 30 docs is roughly the upper bound."

## Symptoms

expected: SEA step produces a valid SEAResult with confirmed_facts, gaps, and verdict fields on all iterations
actual: On iteration 2 (doc_count=21) and iteration 3 (doc_count=30), the LLM response hits max_tokens stop reason, output is truncated, and SEAResult validation fails with missing confirmed_facts and gaps fields
errors: "Output parser received a `max_tokens` stop reason"; ValidationError for SEAResult — confirmed_facts Field required, gaps Field required
reproduction: Fiqh query that triggers 3 iterations with increasing doc counts (5 -> 21 -> 30)
started: Observed in production via Sentry

## Eliminated

## Evidence

- timestamp: 2026-05-25T00:01:00Z
  checked: core/chat_models.py — get_classifier_model()
  found: max_tokens=2048 hardcoded on line 67. This model is shared by SEA (sea.py), decomposer (decomposer.py), and classifier (classifier.py). The SEA step produces the most complex output (SEAResult with nested Finding objects) but shares the same 2048 token budget as simpler classification tasks.
  implication: 2048 tokens is sufficient for classification/decomposition (short outputs) but insufficient for SEA structured output with 21+ evidence documents (each Finding contains a citation quote from the evidence).

- timestamp: 2026-05-25T00:01:30Z
  checked: modules/fiqh/sea.py — _aassess_evidence_call
  found: Uses get_classifier_model().with_structured_output(SEAResult). No max_tokens override at the call site. The structured output must contain: findings (list of Finding with description, confirmed, citation, gap_summary for each), confirmed_facts (list[str]), gaps (list[str]), verdict. With 21 docs, this needs ~15-21 findings with exact citation quotes.
  implication: The output token budget is fixed at 2048 regardless of evidence volume. SEAResult with citations from 21+ docs easily exceeds this.

- timestamp: 2026-05-25T00:02:00Z
  checked: core/resilience.py — anthropic_retry decorator
  found: Only retries on transient Anthropic errors (5xx, 429, connection, timeout). The max_tokens truncation causes a Pydantic ValidationError (not an Anthropic API error), so retries will just hit the same max_tokens limit and fail identically each time.
  implication: Retry logic does not help here — the error is deterministic for a given evidence size, not transient.

- timestamp: 2026-05-25T00:02:30Z
  checked: get_generator_model() in core/chat_models.py
  found: Uses max_tokens=4096 — the fiqh generator already has a higher token budget for producing long answers with evidence citations. This is the appropriate comparison point.
  implication: SEA and generator have similar output complexity (both cite from evidence), but SEA has half the token budget.

## Resolution

root_cause: get_classifier_model() in core/chat_models.py sets max_tokens=2048, which is shared by SEA, decomposer, and classifier. The SEA structured output (SEAResult with nested Finding objects containing exact citation quotes) exceeds 2048 tokens when evidence context is large (21+ docs). The LLM truncates its response at the token limit, LangChain's output parser receives incomplete JSON, and Pydantic validation fails on missing confirmed_facts and gaps fields. Retries do not help because the error is deterministic (same evidence = same truncation).
fix: Add dedicated get_sea_model() in core/chat_models.py with max_tokens=4096 (matching get_generator_model()), and update modules/fiqh/sea.py to use it instead of get_classifier_model().
verification: All 13 SEA unit tests pass. All 64 fiqh unit tests pass (no regressions). 6 pre-existing integration test failures confirmed unrelated (anthropic.OverloadedError attribute + routing logic).
files_changed:
  - core/chat_models.py
  - modules/fiqh/sea.py
  - tests/test_fiqh_sea.py
