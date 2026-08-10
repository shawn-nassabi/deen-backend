# LangGraph Agentic Chat Pipeline

## Overview

This document describes the new agentic chat pipeline that uses LangGraph to enable intelligent, autonomous decision-making instead of a hardcoded sequence of operations.

### Key Innovation

**Before (Hardcoded Pipeline):**
```
Translation → Classification → Enhancement → Retrieval → Generation
```
Every query follows the exact same path, regardless of complexity or content.

**After (Agentic Pipeline):**
```
Agent → [Decides Tools] → [Executes Tools] → [Evaluates] → Response
```
The LLM agent autonomously decides which tools to use, when to use them, and in what order.

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────────┐
│                         Chat Agent                              │
│                                                                 │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐ │
│  │  Fiqh Check  │─────▶│  Agent Node  │─────▶│  Tool Node   │ │
│  │  (Mandatory) │      │  (LLM Brain) │      │  (Execute)   │ │
│  └──────────────┘      └──────────────┘      └──────────────┘ │
│         │                      │                      │         │
│         └──[if fiqh]──> EXIT   └──────────────────────┘         │
│                                   (Decision Loop)                │
│                                          │                       │
│                                   ┌──────▼────────┐             │
│                                   │   Generate    │             │
│                                   │   Response    │             │
│                                   └───────────────┘             │
└─────────────────────────────────────────────────────────────────┘

                    ┌────────────────┐
                    │     Tools      │
                    └────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ┌────▼────┐      ┌─────▼─────┐     ┌─────▼─────┐
   │Classify │      │  Enhance  │     │ Retrieve  │
   │Non-Islam│      │   Query   │     │Documents  │
   └─────────┘      └───────────┘     └───────────┘
```

### State Management

The agent maintains a `ChatState` that tracks:
- **User Query & Context**: Original query, session ID, language preferences
- **Processing Flags**: What has been done (translated, classified, enhanced, retrieved)
- **Results**: Retrieved documents, enhanced query, final response
- **Configuration**: Retrieval parameters, model settings
- **Flow Control**: Early exits, errors, iteration count

### Tool Ecosystem

#### 1. Mandatory Pre-Processing
- **Fiqh Classification**: Automatically checks if query asks for a fiqh ruling (happens before agent)
  - If fiqh-related → Early exit with polite message
  - If not fiqh-related → Proceeds to agent

#### 2. Classification Tools
- **`check_if_non_islamic_tool`**: Determines if query is about Islamic education

#### 3. Translation Tools
- **`translate_to_english_tool`**: Translates non-English queries
- **`translate_response_tool`**: Translates responses to user's language

#### 4. Enhancement Tools
- **`enhance_query_tool`**: Improves query using chat history context

#### 5. Retrieval Tools
- **`retrieve_shia_documents_tool`**: Gets documents from Shia sources
- **`retrieve_sunni_documents_tool`**: Gets documents from Sunni sources
- **`retrieve_combined_documents_tool`**: Gets documents from both sources

## Usage

### Basic Usage (Streaming)

```python
from core.pipeline_langgraph import chat_pipeline_streaming_agentic

response = await chat_pipeline_streaming_agentic(
    user_query="What is Imamate in Shia Islam?",
    session_id="user123:thread-456",
    target_language="english"
)

# Returns a StreamingResponse
```

### With Custom Configuration

```python
from agents.config.agent_config import AgentConfig, RetrievalConfig

# Create custom configuration
config = AgentConfig(
    retrieval=RetrievalConfig(
        shia_doc_count=7,      # Retrieve 7 Shia documents (clamped 1-10 at runtime)
        sunni_doc_count=3      # Retrieve 3 Sunni documents (clamped 0-5 at runtime)
    ),
    model=ModelConfig(
        agent_model="claude-sonnet-4-6",  # Or use LARGE_LLM from environment
        temperature=0.7
    ),
    max_iterations=3,
)

response = await chat_pipeline_streaming_agentic(
    user_query="Explain the concept of Wilayah",
    session_id="user123:thread-456",
    target_language="english",
    config=config
)
```

### API Endpoints

#### 1. Streaming Endpoint (Recommended)

```http
POST /chat/stream/agentic
Content-Type: application/json

{
  "user_query": "What is Tawhid?",
  "session_id": "user123:thread-456",
  "language": "english",
  "config": {
    "retrieval": {
      "shia_doc_count": 5,
      "sunni_doc_count": 2
    }
  }
}
```

Response: Server-Sent Events (SSE) stream with response chunks and references.

#### 2. Non-Streaming Endpoint

```http
POST /chat/agentic
Content-Type: application/json

{
  "user_query": "Tell me about Imam Ali",
  "session_id": "user123:thread-456",
  "language": "english"
}
```

Response:
```json
{
  "response": "Imam Ali ibn Abi Talib...",
  "retrieved_docs": [...],
  "metadata": {
    "iterations": 3,
    "classification_checked": true,
    "query_enhanced": true,
    "retrieval_completed": true,
    "shia_docs_count": 5,
    "sunni_docs_count": 2,
    "errors": []
  }
}
```

## Configuration Options

### RetrievalConfig

```python
class RetrievalConfig(BaseModel):
    shia_doc_count: int = 5           # Number of Shia documents (clamped 1-10 at runtime)
    sunni_doc_count: int = 2          # Number of Sunni documents (clamped 0-5 at runtime)
    quran_doc_count: int = 3          # Number of Quran/Tafsir documents (clamped 0-5)
    # reranking_enabled / dense_weight / sparse_weight were removed in DEE-60:
    # they were never read (the reranker uses DENSE_RESULT_WEIGHT /
    # SPARSE_RESULT_WEIGHT from core.config). Clients still sending them are
    # ignored by pydantic.
```

### ModelConfig

```python
class ModelConfig(BaseModel):
    agent_model: str = LARGE_LLM      # Model for the agent (from environment)
    temperature: float = 0.7          # Generation temperature
    max_tokens: Optional[int] = None  # Max response tokens
```

### AgentConfig

```python
class AgentConfig(BaseModel):
    retrieval: RetrievalConfig        # Retrieval settings
    model: ModelConfig                # Model settings
    max_iterations: int = 3           # Max agent iterations (le=10)
    # enable_classification / enable_translation / enable_enhancement /
    # stream_intermediate_steps were removed in DEE-60 (defined since v1 but
    # never read by any code path). Clients still sending them are ignored.
```

## How the Agent Makes Decisions

The agent uses the system prompt in `agents/prompts/agent_prompts.py` to guide its decision-making:

### Decision Flow

1. **Fiqh Classification (Mandatory)**: Before reaching the agent, every query is checked
   - If fiqh-related (asking for rulings/fatwas) → Early exit with polite message
   - If not fiqh-related → Proceeds to agent
   - This ensures the system stays within its educational scope

2. **Initial Assessment**: Agent reads the user query and decides if classification is needed
   - Most Islamic queries skip classification
   - Only obviously off-topic queries trigger non-Islamic classification

3. **Language Detection**: If query appears non-English, use translation tool

4. **Query Enhancement**: Usually enhances query with chat history context
   - Adds context from conversation
   - Clarifies ambiguous references
   - Expands abbreviations

5. **Document Retrieval**: Chooses retrieval strategy based on query type
   - **Shia-specific topics**: Retrieve Shia documents only
   - **General Islamic topics**: Retrieve both Shia and Sunni
   - **Comparative queries**: May retrieve separately for analysis

6. **Response Generation**: Synthesizes information from retrieved documents

### Example Decision Paths

**Query**: "What is Tawhid?"
```
System: ✓ Fiqh check: NOT fiqh-related → Continue to agent
Agent:  ✓ Clearly Islamic, skip non-Islamic classification
        ✓ English, skip translation
        ✓ Enhance query with context
        ✓ Retrieve 5 Shia + 2 Sunni docs (general topic)
        ✓ Generate comprehensive response
```

**Query**: "Tell me more about him"
```
System: ✓ Fiqh check: NOT fiqh-related → Continue to agent
Agent:  ✓ Skip non-Islamic classification (continuation of conversation)
        ✓ English, skip translation
        ✓ Enhance query (crucial - needs context!)
        → Enhanced: "Tell me more about Imam Ali"
        ✓ Retrieve 5-7 Shia docs (Shia-specific)
        ✓ Generate response
```

**Query**: "Is it halal to eat shrimp?"
```
System: ✓ Fiqh check: IS fiqh-related → Early exit
        → Returns: "This is a fiqh-related question. My capabilities 
                    are not ready yet to answer such queries. Please 
                    consult a qualified scholar."
```

**Query**: "What's for dinner?"
```
System: ✓ Fiqh check: NOT fiqh-related → Continue to agent
Agent:  ✓ Classification needed (suspicious)
        ✓ Check: is_non_islamic = True
        → Early exit with polite message
```

## Benefits of the Agentic Approach

### 1. **Flexibility**
- Adapts to query complexity
- Can handle multi-step reasoning
- Adjusts tool usage based on needs

### 2. **Efficiency**
- Skips unnecessary steps
- No over-classification
- Smart resource usage

### 3. **Extensibility**
- Add new tools without modifying core logic
- Tools are self-documenting
- Easy to test in isolation

### 4. **Observability**
- LangGraph provides built-in tracing
- Clear decision trail
- Easy debugging

### 5. **Configurability**
- Per-request configuration
- User preferences honored
- A/B testing friendly

## Testing

Run the test suite:

```bash
# All tests
pytest agent_tests/test_langgraph_chat.py -v

# Specific test categories
pytest agent_tests/test_langgraph_chat.py -v -m unit
pytest agent_tests/test_langgraph_chat.py -v -m integration

# Individual test classes
pytest agent_tests/test_langgraph_chat.py::TestClassificationTools -v
pytest agent_tests/test_langgraph_chat.py::TestRetrievalTools -v
pytest agent_tests/test_langgraph_chat.py::TestChatAgent -v
```

## Migration Strategy

### Phase 1: Parallel Deployment (Current)
- Both old and new pipelines available
- Old endpoint: `/chat/stream`
- New endpoint: `/chat/stream/agentic`
- No disruption to existing users

### Phase 2: A/B Testing
- Route percentage of traffic to new endpoint
- Monitor performance metrics
- Gather user feedback
- Compare response quality

### Phase 3: Gradual Rollout
- Increase traffic to agentic endpoint
- Address any issues
- Optimize based on learnings

### Phase 4: Full Migration
- Make agentic endpoint the default
- Deprecate old endpoint (with notice)
- Remove old pipeline code

## Troubleshooting

### Agent Takes Too Many Iterations

**Solution**: Adjust `max_iterations` in config
```python
config = AgentConfig(max_iterations=10)
```

### Agent Not Using Certain Tools

**Check**: System prompt in `agents/prompts/agent_prompts.py`
- Ensure tool descriptions are clear
- Add examples if needed
- Consider if the agent's decision is actually correct

### Retrieval Returns Too Few/Many Documents

**Solution**: Configure retrieval counts
```python
config = AgentConfig(
    retrieval=RetrievalConfig(
        shia_doc_count=10,
        sunni_doc_count=5
    )
)
```

### State Not Persisting Across Turns

**Check**: Session ID consistency
- Ensure same `session_id` used for conversation
- Verify Redis connection
- Check checkpointer configuration

## Development Tips

### Adding New Tools

1. Create tool function with `@tool` decorator
2. Add comprehensive docstring (LLM reads this!)
3. Return structured dict with results
4. Add to tool list in `agents/tools/__init__.py`
5. Bind to agent in `agents/core/chat_agent.py`
6. Write tests in `agent_tests/test_langgraph_chat.py`

### Modifying Agent Behavior

1. Edit system prompt in `agents/prompts/agent_prompts.py`
2. Adjust decision logic in `agents/core/chat_agent.py`
3. Test with various query types
4. Monitor LangSmith traces for debugging

### Custom Configuration Per User

```python
# Store user preferences
user_config = {
    "retrieval": {
        "shia_doc_count": user.preferred_doc_count,
        "sunni_doc_count": 0 if user.shia_only else 2
    }
}

# Use in request
response = await chat_pipeline_streaming_agentic(
    user_query=query,
    session_id=session_id,
    config=AgentConfig.from_dict(user_config)
)
```

## Performance Considerations

- **Latency**: Agent adds ~1-2 seconds overhead for decision-making
- **Tokens**: More token usage due to agent reasoning
- **Benefits**: Often faster overall due to skipping unnecessary steps

## Future Enhancements

- [ ] Add more specialized tools (hadith grading, scholar lookup)
- [ ] Implement memory consolidation as a tool
- [ ] Add multi-turn dialogue management
- [ ] Tool result caching for common queries
- [ ] Parallel tool execution where possible
- [ ] Automatic prompt optimization based on performance

## References

- **LangGraph Documentation**: https://langchain-ai.github.io/langgraph/
- **LangChain Tools**: https://python.langchain.com/docs/modules/agents/tools/
- **Existing Pipeline**: `core/pipeline.py`

## Support

For questions or issues with the agentic pipeline:
1. Check this README
2. Review test cases in `agent_tests/test_langgraph_chat.py`
3. Examine LangSmith traces (if enabled)
4. Contact the development team

---

**Built with LangGraph** | **Powered by Anthropic Claude** | **For Islamic Education**





