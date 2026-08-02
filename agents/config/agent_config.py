"""
Configuration classes for the LangGraph agentic pipeline.
"""

from pydantic import BaseModel, Field
from core.config import LARGE_LLM


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
    
    # Token-cost DEE-60 Phase 1: enable_classification / enable_translation /
    # enable_enhancement / stream_intermediate_steps were removed — defined
    # since the first agent version but never read by any code path. Clients
    # that still send them are ignored by pydantic (extra='ignore' default).

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
        """Create config from dictionary."""
        return cls(**data)


# Default configuration instance
DEFAULT_AGENT_CONFIG = AgentConfig()




