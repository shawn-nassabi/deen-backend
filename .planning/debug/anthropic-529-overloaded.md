---
status: awaiting_human_verify
trigger: "Sentry catching OverloadedError 529 from Anthropic API during /chat/stream/agentic. SDK retries exhaust after ~50s, exception propagates unhandled through LangChain into pipeline."
created: 2026-05-25T00:00:00Z
updated: 2026-05-25T00:00:00Z
---

## Current Focus

reasoning_checkpoint:
  hypothesis: "OverloadedError propagates to user as generic error because (1) agent LLM lacks max_retries/timeout config, (2) streaming .astream() calls are unprotected by retry, (3) pipeline error handler does not differentiate transient API overload from other errors."
  confirming_evidence:
    - "chat_agent.py line 72-76: ChatAnthropic() called without max_retries or timeout"
    - "core/resilience.py line 13: explicitly states streaming .astream must NOT be wrapped"
    - "pipeline_langgraph.py line 529: generic 'An error occurred' for ALL exceptions including OverloadedError"
    - "core/chat_models.py: all other models use max_retries=5, timeout=60 — proving this was intentional elsewhere but missed for agent LLM"
  falsification_test: "If the agent LLM already had max_retries=5 and the pipeline had overload-specific error messaging, the Sentry trace would not show the error propagating."
  fix_rationale: "Fix addresses all three root causes: (1) add max_retries=5 and timeout=60 to agent LLM, (2) add overload-specific error handling in pipeline error handler to emit a user-friendly 'busy' message, (3) keep logging for observability. Does not wrap .astream in retry (correctly, per streaming design)."
  blind_spots: "Sustained overloads beyond the combined retry budget will still fail — but with proper user messaging. The fiqh and hadith .astream paths still won't retry internally (by design — partial output)."

next_action: "Apply three-part fix: (1) add max_retries/timeout to ChatAgent LLM, (2) add overload-specific error detection in pipeline_langgraph error handler, (3) emit specific user-facing error message for transient API errors."

## Symptoms

expected: "Anthropic API 529 overload errors should be retried with sufficient attempts and backoff. If retries exhaust, user should receive a clear message indicating the AI service is temporarily busy."
actual: "SDK retries 6 times with exponential backoff but exhausts after ~50s. OverloadedError propagates through LangChain into pipeline. User gets generic 'An error occurred. Please try again.' error via SSE."
errors: "OverloadedError: Error code: 529 — propagated through langchain_anthropic → pipeline_langgraph → Sentry"
reproduction: "Occurs during Anthropic API overload periods on /chat/stream/agentic endpoint"
started: "Observed in production Sentry"

## Eliminated

## Evidence

- timestamp: 2026-05-25T00:01:00Z
  checked: "agents/core/chat_agent.py _create_llm_with_tools()"
  found: "ChatAnthropic initialized WITHOUT max_retries or timeout parameters (line 72-76). Only model, api_key, temperature, max_tokens are set."
  implication: "langchain-anthropic defaults to max_retries=2, which is insufficient for sustained overload (Sentry shows 6 retries needed). The agent tool-calling LLM has weaker retry config than the generator models in core/chat_models.py which use max_retries=5."

- timestamp: 2026-05-25T00:02:00Z
  checked: "core/chat_models.py get_generator_model() et al"
  found: "All generator/classifier/enhancer/translator models set max_retries=5, timeout=60s (lines 43-44, 53-54, 63-64, 78-79). The agent LLM does NOT."
  implication: "Inconsistency: tool-calling agent LLM (most critical path) has weakest retry config."

- timestamp: 2026-05-25T00:03:00Z
  checked: "core/resilience.py anthropic_retry decorator"
  found: "Decorator wraps .ainvoke() calls with 3 attempts, exponential jitter 0.5-8s. Used by _retry_ainvoke in chat_agent.py. But explicitly states 'Streaming call sites (.astream) MUST NOT be wrapped' (line 13)."
  implication: "The .astream() calls in pipeline_langgraph.py (lines 386, 454) for token streaming are NOT covered by anthropic_retry. If overload hits during streaming generation, it propagates directly."

- timestamp: 2026-05-25T00:04:00Z
  checked: "core/pipeline_langgraph.py error handling (lines 494-531)"
  found: "Broad except Exception catches ALL errors including OverloadedError. Emits generic 'An error occurred. Please try again.' No differentiation between transient overload vs permanent errors."
  implication: "User gets no indication that the issue is temporary/overload-specific. No specific messaging like 'service is temporarily busy'."

- timestamp: 2026-05-25T00:05:00Z
  checked: "agents/core/chat_agent.py _agent_node error handling (lines 216-219)"
  found: "Catches Exception, appends to state['errors'], sets should_end=True. Does not differentiate OverloadedError. The _retry_ainvoke wrapper has 3 attempts (from resilience.py default), plus the SDK's own 2 retries = total ~5-6 attempts before final exception."
  implication: "Combined retry strategy: SDK does 2 retries internally, then tenacity does 3 attempts of the full SDK call (each of which does its own 2 retries). This means up to 6 SDK-level attempts. But the SDK retry timing is short — adding max_retries=5 to SDK level would give better backoff."

## Resolution

root_cause: "Three compounding issues cause poor OverloadedError UX: (1) ChatAgent LLM init lacks max_retries/timeout, defaulting to SDK's 2 retries (too few for sustained overload); (2) Streaming .astream() paths for token generation are not covered by anthropic_retry and have no overload-specific error handling; (3) Pipeline error handler emits a generic error message without distinguishing transient overload from permanent failures."
fix: "Three-part fix: (1) Added max_retries=5, timeout=60 to ChatAgent LLM init to match core/chat_models.py config. (2) Added _is_transient_llm_error() helper in pipeline_langgraph.py that walks the exception cause chain to detect OverloadedError/RateLimitError/APIConnectionError/APITimeoutError/InternalServerError. (3) Updated the pipeline streaming error handler to emit a user-friendly 'Our AI service is temporarily busy' SSE error with retry=True flag for transient errors, keeping the generic message for non-transient errors."
verification: "All 248 passing tests still pass. _is_transient_llm_error correctly identifies: OverloadedError(529)=True, RateLimitError(429)=True, APIConnectionError=True, APITimeoutError=True, InternalServerError(500)=True, BadRequestError(400)=False, ValueError=False, wrapped OverloadedError via __cause__=True."
files_changed:
  - agents/core/chat_agent.py
  - core/pipeline_langgraph.py
