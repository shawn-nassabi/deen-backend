# Requirements: Deen Backend v1.4 — LLM Input Caching

**Defined:** 2026-05-03
**Core Value:** Every fiqh answer must be strictly grounded in retrieved evidence from Ayatollah Sistani's published rulings — the system refuses to answer rather than hallucinate or speculate.

## v1.4 Requirements

### Caching — ChatAgent path

- [ ] **CACHE-01**: ChatAgent tool definitions (6 tools) are sent to the Anthropic API with `cache_control` on every `/chat/stream/agentic` request
- [ ] **CACHE-02**: ChatAgent system prompt is sent as a structured content-block list with `cache_control` at `_agent_node` and `_generate_response_node`
- [ ] **CACHE-03**: Tests confirm `cache_creation_input_tokens > 0` on the first call and `cache_read_input_tokens > 0` on a second identical call within the 5-minute TTL window
- [ ] **CACHE-04**: Cache metrics (`cache_read_tokens`, `cache_creation_tokens`, `cache_hit`) are emitted per ChatAgent call via `logger.debug(..., extra={..., "correlation_id": ...})`

### Structural Refactoring — module system prompts

- [ ] **STRUCT-01**: A `make_cached_system_message(text: str) -> SystemMessage` helper is added to `core/chat_models.py` as the single construction point for cached system messages
- [ ] **STRUCT-02**: All `ChatPromptTemplate` system-message patterns in `modules/fiqh/` (6 files), `modules/classification/` (1 file), `modules/translation/` (1 file), and `core/prompt_templates.py` (4 templates) are refactored to `SystemMessage(content=[...])` content-block format with `cache_control` — zero behavioral change; `modules/enhancement/enhancer.py` is explicitly excluded

### Observability

- [ ] **OBS-01**: Per-session cache efficiency ratio (`cache_read_tokens / (cache_read_tokens + cache_creation_tokens)`) is emitted as a Sentry breadcrumb for each completed chat session
- [ ] **OBS-02**: Linear ticket DEE-50 is updated with implementation details (eligible call sites, approach taken) and measured cache hit rates after deployment verification

## Future Requirements

### Multi-turn history caching

- **HIST-01**: Second `cache_control` breakpoint applied to accumulated message history prefix for sessions exceeding ~10 turns — defer until Phase 1 hit rates are confirmed in production

### Legacy path caching

- **LEGACY-01**: Legacy generator system prompt (`modules/generation/generator.py`) cached if token count is confirmed above 2,048 minimum at implementation time — borderline at ~1,200 tokens estimated

## Out of Scope

| Feature | Reason |
|---------|--------|
| Caching `modules/enhancement/enhancer.py` | Uses Haiku 4.5 which requires 4,096 token minimum; enhancer system prompt is ~330 tokens — applying `cache_control` would charge 1.25× write cost on every call with zero cache hits |
| Caching `ToolMessage.content[]` blocks (retrieved docs) | Confirmed API error: `invalid_cache` at `messages.N.content.0.content.0.cache_control` (GitHub #34920); retrieved documents are dynamic anyway |
| `AnthropicPromptCachingMiddleware` | Does not exist in `langchain-anthropic==0.3.22`; incompatible with `bind_tools()` regardless |
| Upgrading `langchain-anthropic` to 1.x | Requires `langchain>=1.0` — separate major-version migration outside this milestone's scope |
| Caching across different users/sessions | Anthropic caches by exact prefix content; user-specific injections in prompts would break the cache key |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CACHE-01 | — | Pending |
| CACHE-02 | — | Pending |
| CACHE-03 | — | Pending |
| CACHE-04 | — | Pending |
| STRUCT-01 | — | Pending |
| STRUCT-02 | — | Pending |
| OBS-01 | — | Pending |
| OBS-02 | — | Pending |

**Coverage:**
- v1.4 requirements: 8 total
- Mapped to phases: 0 (roadmap pending)
- Unmapped: 8 ⚠

---
*Requirements defined: 2026-05-03*
*Last updated: 2026-05-03 after initial definition*
