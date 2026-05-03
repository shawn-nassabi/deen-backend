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
    this message as a single prefix (tools + system prompt). Requires combined token
    count >= 2048 for claude-sonnet-4-6.
    """
    return SystemMessage(content=[
        {
            "type": "text",
            "text": text,
            "cache_control": {"type": "ephemeral"},
        }
    ])


def get_generator_model():
    """Returns ChatAnthropic for long-form generation (fiqh answers, general responses)."""
    from core.config import LARGE_LLM
    return ChatAnthropic(model=LARGE_LLM, api_key=ANTHROPIC_API_KEY, max_tokens=4096)


def get_enhancer_model():
    """Returns ChatAnthropic for query enhancement (short rewrites)."""
    from core.config import SMALL_LLM
    return ChatAnthropic(model=SMALL_LLM, api_key=ANTHROPIC_API_KEY, max_tokens=512)


def get_classifier_model():
    """Returns ChatAnthropic for fiqh classification and SEA structured output."""
    from core.config import LARGE_LLM
    return ChatAnthropic(model=LARGE_LLM, api_key=ANTHROPIC_API_KEY, max_tokens=2048)


def get_translator_model():
    """Returns ChatAnthropic bound to temperature=0 for deterministic translation."""
    from core.config import LARGE_LLM
    base = ChatAnthropic(model=LARGE_LLM, api_key=ANTHROPIC_API_KEY, max_tokens=1024)
    return base.bind(temperature=0)
