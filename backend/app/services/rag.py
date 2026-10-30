import logging
import re

from app.core.config import settings
from app.services.llm import generate_grounded_answer
from app.services.retrieval import semantic_search


logger = logging.getLogger(__name__)

NO_ANSWER = (
    "I couldn't find enough information in the uploaded "
    "documents to answer that question."
)


def _prepare_context(
    retrieved: list[dict],
) -> tuple[list[dict], list[dict]]:
    """
    Prepare source references for the LLM.

    Returns:
        context_sources: bounded source passages sent to the model.
        display_sources: corresponding metadata returned to the UI.
    """

    context_sources = []
    display_sources = []

    total_chars = 0
    max_chars = settings.rag_max_context_chars
    max_chunks = settings.rag_max_context_chunks

    for item in retrieved:
        if len(context_sources) >= max_chunks:
            break

        text = item.get("content", "").strip()

        if not text:
            continue

        remaining = max_chars - total_chars

        if remaining <= 0:
            break

        # The model context is limited, but the UI can receive
        # the complete retrieved passage.
        context_text = text[:remaining]

        source_ref = f"S{len(context_sources) + 1}"

        context_source = {
            "source_ref": source_ref,
            "filename": item["filename"],
            "page_number": item["page_number"],
            "content": context_text,
        }

        display_source = {
            **item,
            "source_ref": source_ref,
        }

        context_sources.append(context_source)
        display_sources.append(display_source)

        total_chars += len(context_text)

    return context_sources, display_sources


def answer_question(
    query: str,
    top_k: int | None = None,
) -> dict:
    """
    Execute semantic retrieval and grounded answer generation.

    This stage does not use keyword search or hybrid ranking.
    """

    query = query.strip()

    if not query:
        raise ValueError("The question cannot be empty.")

    # Step 1: Retrieve relevant passages.
    retrieved = semantic_search(
        query=query,
        top_k=top_k,
    )

    # Step 2: Handle absent evidence without calling the LLM.
    if not retrieved:
        logger.info(
            "No semantic evidence found for a query."
        )

        return {
            "query": query,
            "answer": NO_ANSWER,
            "citations": [],
            "not_found": True,
            "retrieval_mode": "semantic",
            "results": [],
        }

    # Step 3: Bound the context and assign source IDs.
    context_sources, display_sources = _prepare_context(
        retrieved
    )

    if not context_sources:
        return {
            "query": query,
            "answer": NO_ANSWER,
            "citations": [],
            "not_found": True,
            "retrieval_mode": "semantic",
            "results": [],
        }

    # Step 4: Generate a structured, grounded answer locally.
    generated = generate_grounded_answer(
        query=query,
        sources=context_sources,
    )

    valid_refs = {
        source["source_ref"]
        for source in context_sources
    }

    citations = [
        reference
        for reference in generated["citations"]
        if reference in valid_refs
    ]

    citations = list(dict.fromkeys(citations))

    answer = generated["answer"].strip()

    # Step 5: Never return an unsupported or uncited answer.
    if (
        generated["not_found"]
        or not answer
        or not citations
    ):
        return {
            "query": query,
            "answer": NO_ANSWER,
            "citations": [],
            "not_found": True,
            "retrieval_mode": "semantic",
            # Candidate passages remain available for inspection.
            "results": display_sources,
        }

    # Keep citation formatting under backend control.
    # The model provides citation IDs; the backend verifies them.
    answer = re.sub(
        r"\[S\d+\]",
        "",
        answer,
    ).strip()

    answer = (
        f"{answer}\n\nSources: "
        + ", ".join(f"[{ref}]" for ref in citations)
    )

    # Display the passages actually cited by the model.
    cited_sources = [
        source
        for source in display_sources
        if source["source_ref"] in citations
    ]

    logger.info(
        "Generated a grounded answer with %s cited sources.",
        len(cited_sources),
    )

    return {
        "query": query,
        "answer": answer,
        "citations": citations,
        "not_found": False,
        "retrieval_mode": "semantic",
        "results": cited_sources,
    }