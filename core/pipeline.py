import asyncio
from itertools import chain
import json

from fastapi.responses import StreamingResponse

from core import utils
from core.config import REFERENCE_FETCH_COUNT
from modules.classification import classifier
from modules.embedding import embedder
from modules.enhancement import enhancer
from modules.generation import generator, stream_generator
from modules.retrieval import retriever
from modules.translation import translator

# Not updated for memory persistence yet
def chat_pipeline(user_query: str, session_id: str):
    # # Step 1: Classify query (fiqh or non-fiqh)
    is_non_islamic = classifier.classify_non_islamic_query(user_query)
    if is_non_islamic:
        return "This question is not related to the domain of Islamic education. Please ask relevant questions."
    

    # # Step 2: Classify query (fiqh or non-fiqh)
    is_fiqh = classifier.classify_fiqh_query(user_query)
    
    if is_fiqh:
        return "This is a fiqh-related question. Please consult a qualified scholar."
    
    # Step 3: Enhance query
    enhanced_query = enhancer.enhance_query(user_query)

    # Step 4: Retrieve relevant documents from Pinecone
    relevant_docs = retriever.retrieve_documents(enhanced_query,REFERENCE_FETCH_COUNT)

    # Step 5: Generate AI response using LLM
    ai_response = generator.generate_response(enhanced_query, relevant_docs)

    return ai_response


# Updated for in-chat memory persistence
def chat_pipeline_streaming(user_query: str, session_id: str, target_language: str = "english"):
    

    # Step 1: Translate user query from target language to english (if needed)
    tl = (target_language or "english").strip().lower()
    if tl != "english":
        try:
            user_query = translator.translate_to_english(user_query, tl)
        except Exception as e:
            # Log the error but don’t break the pipeline
            print(f"[chat_pipeline_streaming] Translation failed: {e}")
            # Fallback: keep the original user_query

    # Step 2: Classify the query
    is_non_islamic = classifier.classify_non_islamic_query(user_query, session_id=session_id)
    if is_non_islamic:
        message = "I am not allowed to answer that question. I specialize in questions related to Twelver Shia Islam, anything from history, to theology, to interpretations, and more... Please try another one."
        return StreamingResponse(utils.stream_message(message), media_type="text/event-stream")

    is_fiqh = classifier.classify_fiqh_query(user_query, session_id=session_id)
    if is_fiqh:
        message = "This is a fiqh-related question. My capabilities are not ready yet to answer such queries. Please consult a qualified scholar."
        return StreamingResponse(utils.stream_message(message), media_type="text/event-stream")

    # Step 3: Enhance the query (with chat history context if available)
    enhanced_query = enhancer.enhance_query(user_query, session_id)

    # Step 4: Retrieve relevant documents from Pinecone
    # relevant_docs = retriever.retrieve_documents(enhanced_query, 5) # NOTE: Changed to 5 references for chatbot
    relevant_shia_docs = retriever.retrieve_shia_documents(enhanced_query, 5)
    relevant_sunni_docs = retriever.retrieve_sunni_documents(enhanced_query, 2)

    all_relevant_docs = relevant_shia_docs + relevant_sunni_docs

    # Step 5: Stream the AI response from the LLM
    response_generator = stream_generator.generate_response_stream(user_query, all_relevant_docs, session_id, target_language=tl)

    #Step 6: Stream the formatted references in JSON format
    references_tail = utils.stream_message('\n\n\n[REFERENCES]\n\n\n' + json.dumps(utils.format_references_as_json(all_relevant_docs)))

    # Return a StreamingResponse with appropriate media type.
    return StreamingResponse(chain(response_generator, references_tail), media_type="text/event-stream")



async def references_pipeline(user_query: str, sect: str, limit: int = REFERENCE_FETCH_COUNT, language: str = "english"):
    """Async references pipeline (DEE-44). Uses native `aclassify_*`,
    `aenhance_query`, and `aretrieve_*` so the route doesn't block the event
    loop on classification → enhancement → retrieval → ranking.

    `language` (DEE-67) threads through to `utils.aformat_references_as_json`,
    which joins in a selected-language translation from the Postgres sidecar
    table -- retrieval/ranking above is unaffected."""
    is_non_islamic = await classifier.aclassify_non_islamic_query(user_query)
    if is_non_islamic:
        return "This question is not related to the domain of Islamic education. Please ask relevant questions."

    enhanced_query = await enhancer.aenhance_query(user_query)

    results: dict = {}
    fetches = []
    if sect in ["shia", "both"]:
        fetches.append(("shia", retriever.aretrieve_shia_documents(enhanced_query, limit)))
    if sect in ["sunni", "both"]:
        fetches.append(("sunni", retriever.aretrieve_sunni_documents(enhanced_query, limit)))

    # Run shia + sunni retrievals concurrently when both are requested.
    fetched = await asyncio.gather(*[fut for _, fut in fetches])
    for (label, _), docs in zip(fetches, fetched):
        results[label] = await utils.aformat_references_as_json(docs, language)

    return results


async def hikmah_elaboration_pipeline_streaming(selected_text: str, context_text: str, hikmah_tree_name: str, lesson_name: str, lesson_summary: str, user_id: str = None):
    """Async hikmah elaboration streaming pipeline (DEE-44)."""
    relevant_shia_docs = await retriever.aretrieve_shia_documents(context_text, 4)

    response_generator = stream_generator.agenerate_elaboration_response_stream(
        selected_text,
        context_text,
        hikmah_tree_name,
        lesson_name,
        lesson_summary,
        relevant_shia_docs,
        user_id=user_id,
    )

    return StreamingResponse(response_generator, media_type="text/event-stream")