from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from core.config import ANTHROPIC_API_KEY


def make_cached_system_message(text: str) -> SystemMessage:
    """Returns a SystemMessage with cache_control for Anthropic prompt caching.

    Uses structured content-block format (list of dicts) rather than a plain string.
    This is required because ChatPromptTemplate.format_messages() strips cache_control
    from plain-string content (GitHub #26701). The list format preserves cache_control
    through LangChain's Anthropic integration.

    The cache_control breakpoint tells Anthropic to cache everything up to and including
    this message as a single prefix (tools + system prompt). Minimum cacheable prefix
    for claude-sonnet-4-6 is 1024 tokens per current Anthropic docs (the old 2048 note
    here was stale) — treat runtime `cache_creation_input_tokens > 0` as ground truth.
    Prefixes below the minimum silently don't cache.
    """
    return SystemMessage(content=[
        {
            "type": "text",
            "text": text,
            "cache_control": {"type": "ephemeral"},
        }
    ])


# DEE-51: explicit retry + timeout config across every ChatAnthropic.
# langchain-anthropic defaults to max_retries=2 with no app-level timeout —
# too tight for production overload spikes (529 / 503 / 429). 5 retries with
# a 60s per-request timeout absorbs typical transient incidents within the
# SSE no-proxy-timeout budget.
_ANTHROPIC_MAX_RETRIES = 5
_ANTHROPIC_TIMEOUT_S = 60


def get_generator_model():
    """Returns ChatAnthropic for long-form generation (fiqh answers, general responses)."""
    from core.config import LARGE_LLM
    return ChatAnthropic(
        model=LARGE_LLM,
        api_key=ANTHROPIC_API_KEY,
        max_tokens=4096,
        max_retries=_ANTHROPIC_MAX_RETRIES,
        timeout=_ANTHROPIC_TIMEOUT_S,
    )


def get_enhancer_model():
    """Returns ChatAnthropic for query enhancement (short rewrites)."""
    from core.config import SMALL_LLM
    return ChatAnthropic(
        model=SMALL_LLM,
        api_key=ANTHROPIC_API_KEY,
        max_tokens=512,
        max_retries=_ANTHROPIC_MAX_RETRIES,
        timeout=_ANTHROPIC_TIMEOUT_S,
    )


def get_classifier_model():
    """Returns ChatAnthropic for fiqh classification and decomposition (short outputs)."""
    from core.config import LARGE_LLM
    return ChatAnthropic(
        model=LARGE_LLM,
        api_key=ANTHROPIC_API_KEY,
        max_tokens=2048,
        max_retries=_ANTHROPIC_MAX_RETRIES,
        timeout=_ANTHROPIC_TIMEOUT_S,
    )


def get_sea_model():
    """Returns ChatAnthropic for SEA (Structured Evidence Assessment).

    Uses max_tokens=4096 because SEAResult structured output includes
    per-finding citation quotes that scale with evidence volume.  With 20+
    docs the output easily exceeds the 2048 budget of get_classifier_model(),
    causing a max_tokens truncation that breaks the output parser.
    """
    from core.config import LARGE_LLM
    return ChatAnthropic(
        model=LARGE_LLM,
        api_key=ANTHROPIC_API_KEY,
        max_tokens=4096,
        max_retries=_ANTHROPIC_MAX_RETRIES,
        timeout=_ANTHROPIC_TIMEOUT_S,
    )


def get_translator_model():
    """Returns ChatAnthropic bound to temperature=0 for deterministic translation."""
    from core.config import LARGE_LLM
    base = ChatAnthropic(
        model=LARGE_LLM,
        api_key=ANTHROPIC_API_KEY,
        max_tokens=1024,
        max_retries=_ANTHROPIC_MAX_RETRIES,
        timeout=_ANTHROPIC_TIMEOUT_S,
    )
    return base.bind(temperature=0)
