"""
Configuration classes for the LangGraph agentic pipeline.
"""

import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
from core.config import LARGE_LLM

logger = logging.getLogger(__name__)


class RetrievalConfig(BaseModel):
    """Configuration for document retrieval."""
    
    shia_doc_count: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of Shia documents to retrieve"
    )
    
    sunni_doc_count: int = Field(
        default=2,
        ge=0,
        le=20,
        description="Number of Sunni documents to retrieve"
    )

    quran_doc_count: int = Field(
        default=3,
        ge=0,
        le=20,
        description="Number of Quran/Tafsir documents to retrieve"
    )
    
    # Token-cost DEE-60 Phase 1: reranking_enabled / dense_weight /
    # sparse_weight were removed — they were never read anywhere (the
    # reranker reads DENSE_RESULT_WEIGHT / SPARSE_RESULT_WEIGHT from
    # core.config directly). Clients that still send them are ignored by
    # pydantic (extra='ignore' default).

    class Config:
        json_schema_extra = {
            "example": {
                "shia_doc_count": 5,
                "sunni_doc_count": 2,
                "quran_doc_count": 3
            }
        }


class ModelConfig(BaseModel):
    """Configuration for LLM models."""
    
    agent_model: str = Field(
        default=LARGE_LLM or "claude-sonnet-4-6",
        description="Model to use for the agent (tool calling)"
    )
    
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Temperature for response generation"
    )
    
    max_tokens: int = Field(
        default=4096,
        ge=1,
        description="Maximum tokens for response generation"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "agent_model": LARGE_LLM or "claude-sonnet-4-6",
                "temperature": 0.7,
                "max_tokens": 4096
            }
        }


class AgentConfig(BaseModel):
    """Complete configuration for the agentic chat pipeline."""
    
    retrieval: RetrievalConfig = Field(
        default_factory=RetrievalConfig,
        description="Retrieval configuration"
    )
    
    model: ModelConfig = Field(
        default_factory=ModelConfig,
        description="Model configuration"
    )
    
    max_iterations: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum number of agent iterations"
    )

    # DEE-61a: reintroduced (removed as dead in DEE-60, now actually read by
    # ChatAgent.__init__ to decide whether enhance_query_tool is bound).
    # Default True preserves current behaviour when the field is omitted.
    enable_enhancement: bool = Field(
        default=True,
        description="Whether the agent may call enhance_query_tool"
    )

    # Token-cost DEE-60 Phase 1: enable_classification / enable_translation /
    # stream_intermediate_steps remain removed — defined since the first
    # agent version but never read by any code path. Clients that still
    # send them are ignored by pydantic (extra='ignore' default).

    class Config:
        json_schema_extra = {
            "example": {
                "retrieval": {
                    "shia_doc_count": 5,
                    "sunni_doc_count": 2,
                    "quran_doc_count": 3
                },
                "model": {
                    "agent_model": LARGE_LLM or "claude-sonnet-4-6",
                    "temperature": 0.7
                },
                "max_iterations": 3
            }
        }
    
    def to_dict(self):
        """Convert config to dictionary for storage in state."""
        return self.model_dump()
    
    @classmethod
    def from_dict(cls, data: dict) -> "AgentConfig":
        """Create config from dictionary.

        Token-cost DEE-60: max_iterations is clamped into [1, 10] instead of
        letting an out-of-range value fail validation — older clients sent 15
        (it was previously documented), and a ValidationError here would make
        api/chat.py silently discard the client's ENTIRE config (retrieval
        counts, model overrides) in its fallback path.
        """
        if isinstance(data, dict) and "max_iterations" in data:
            data = dict(data)
            try:
                data["max_iterations"] = max(1, min(int(data["max_iterations"]), 10))
            except (TypeError, ValueError):
                data.pop("max_iterations")  # let the field default apply
        return cls(**data)


# Default configuration instance
DEFAULT_AGENT_CONFIG = AgentConfig()


# ---------------------------------------------------------------------------
# DEE-61a: effort_level -> AgentConfig resolution
# ---------------------------------------------------------------------------


def _agent_config_from_effort_level(effort_level: str) -> AgentConfig:
    """Base AgentConfig derived from the request's effort_level, before any
    explicit client `config` override is applied.

    "high" reproduces DEFAULT_AGENT_CONFIG exactly (current behaviour).
    "quick" trims iterations/retrieval/enhancement for lower latency —
    generation-tier knobs (model swap, max_tokens) are out of scope (DEE-61b).
    """
    if effort_level == "quick":
        return AgentConfig(
            retrieval=RetrievalConfig(
                # ~50% of the "high" defaults (5/2/3), floored at each
                # field's own minimum.
                shia_doc_count=2,
                sunni_doc_count=1,
                quran_doc_count=2,
            ),
            max_iterations=1,
            enable_enhancement=False,
        )
    return AgentConfig()


def _deep_merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge `override` onto `base`, only touching keys present
    in `override`. Equivalent to applying `override` as if it were produced
    by `model_dump(exclude_unset=True)` on top of `base` — fields the client
    never mentioned keep whatever `base` (the effort-derived config) set."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def resolve_agent_config(effort_level: str, config_dict: Optional[Dict[str, Any]]) -> AgentConfig:
    """Single source of truth for merging effort_level + explicit client
    `config` into one AgentConfig. Used by both /chat/stream/agentic and
    /chat/agentic so the precedence rule lives in exactly one place.

    Precedence: effort_level sets the baseline (see
    `_agent_config_from_effort_level`); any field the client explicitly sent
    in `config` overrides the corresponding effort-derived value; fields the
    client did not send keep the effort-derived value. E.g.
    config={"max_iterations": 5} with effort_level="quick" yields
    max_iterations=5 but enable_enhancement stays False (quick's value),
    because "enable_enhancement" was never present in config_dict.

    On a malformed config_dict, falls back to the pure effort-derived config
    (the client's config is discarded, not the effort_level too).
    """
    base = _agent_config_from_effort_level(effort_level)
    if not config_dict:
        return base
    try:
        merged_dict = _deep_merge_dicts(base.to_dict(), config_dict)
        return AgentConfig.from_dict(merged_dict)
    except Exception:
        logger.warning(
            "Config parse error, falling back to effort-derived config",
            extra={"effort_level": effort_level},
        )
        return base




