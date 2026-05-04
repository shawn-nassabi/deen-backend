# Phase 18: Module Prompt Restructuring - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-03
**Phase:** 18-module-prompt-restructuring
**Areas discussed:** core/prompt_templates.py API, Dynamic system prompts, MessagesPlaceholder handling, Memory agent prompts

---

## core/prompt_templates.py API

| Option | Description | Selected |
|--------|-------------|----------|
| Builder functions | Replace each ChatPromptTemplate export with a plain function returning `list[BaseMessage]`. Callers change from `.invoke({}).to_messages()` to calling the function directly. | ✓ |
| Keep ChatPromptTemplate for human messages | Keep a ChatPromptTemplate for the human/placeholder parts only; prepend `make_cached_system_message()` at call sites. | |

**User's choice:** Builder functions
**Notes:** Clear, explicit pattern. No hidden stripping risk. Matches Phase 17 philosophy of direct message construction.

### Fiqh module sub-question: inline vs. private function

| Option | Description | Selected |
|--------|-------------|----------|
| Inline at call site | Remove `_prompt` object entirely; construct list directly at `model.invoke(...)`. | |
| Private builder function `_build_messages` | Add a private `_build_messages(...)` function per module; call sites use it. | ✓ |

**User's choice:** Private builder function per module
**Notes:** Consistent with the `core/prompt_templates.py` builder function pattern across the codebase.

---

## Dynamic System Prompts

| Option | Description | Selected |
|--------|-------------|----------|
| Plain `SystemMessage` for dynamic prompts | Use `SystemMessage(content=formatted_text)` for prompts whose system message contains runtime variables. Avoids guaranteed +25% cache write overhead on dynamic content. | ✓ |
| `make_cached_system_message` uniformly | Apply to all system prompts regardless. Code consistency but accepts cache write overhead every call on dynamic content. | |
| Refactor dynamic parts to human message | Move `{references}`, `{context_text}` etc. out of system body into human message. Makes system static and cacheable. | |

**User's choice:** Plain `SystemMessage` for dynamic prompts
**Notes:** User asked for recommendation + rationale. Recommendation: plain `SystemMessage` because Sonnet cache writes cost 25% more than regular input tokens; hikmah elaboration system template embeds full per-call lesson context (~2000+ tokens), guaranteeing wasteful cache writes with zero hits. User accepted the recommendation. Refactoring dynamic parts to human message was noted as a future optimization (deferred).

---

## MessagesPlaceholder Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Update stream_generator.py to fetch history explicitly | Change `generate_response_stream()` to call `make_history(session_id).messages` and pass as a list. Remove `with_redis_history()` dependency. Matches what `pipeline_langgraph.py` already does. | ✓ |
| Leave generator_prompt_template as ChatPromptTemplate | Keep as-is with `MessagesPlaceholder`; mark as explicit exclusion with comment. | |

**User's choice:** Update stream_generator.py to fetch history explicitly
**Notes:** `pipeline_langgraph.py` already demonstrates the explicit history pattern — `stream_generator.py` aligning to this is a simplification, not a behavior change.

---

## Memory Agent Prompts (Out of Scope?)

| Option | Description | Selected |
|--------|-------------|----------|
| Leave as-is, add to backlog | Memory prompts not in Phase 18 ROADMAP success criterion. Backlog item for follow-up sweep. | ✓ |
| Sweep in — expand Phase 18 scope | Include the 4 memory prompt files in Phase 18. Eliminates anti-pattern from entire codebase in one shot. | |

**User's choice:** Leave as-is, add to backlog
**Notes:** Phase 18 success criterion is scoped to `modules/fiqh/`, `modules/classification/`, `modules/translation/`, and `core/prompt_templates.py` — memory agent prompts are not mentioned.

---

## Claude's Discretion

- Exact function signatures for builder functions in `core/prompt_templates.py` — parameter names should match existing template variable names
- Whether to keep old ChatPromptTemplate variable names as comments or delete entirely (preference: clean deletion)

## Deferred Ideas

- **Memory agent prompt sweep** — `agents/prompts/memory_prompts.py` (3 calls) + `agents/core/universal_memory_agent.py` (1 call). Out of Phase 18 scope. Add to backlog.
- **Move dynamic variables out of system message body** — Making `generator` and `hikmah_elaboration` system prompts static and cacheable by moving `{references}`, `{target_language}`, lesson context into human message. Larger behavioral change; future optimization phase.
