import logging
import re
from collections import defaultdict

from app.core.config import settings
from app.db import sqlite_store
from app.services.citations import quote_matches_source
from app.services.hybrid_retrieval import hybrid_search
from app.services.llm import generate_grounded_answer


logger = logging.getLogger(__name__)

DOCUMENT_OVERVIEW_PATTERNS = (
    re.compile(
        r"\b(?:tell|describe|summari[sz]e|summary|overview|explain)\b"
        r".*\b(?:file|document|pdf)s?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:file|document|pdf)s?\b.*"
        r"\b(?:about|contain|cover|overview|summary)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhat\b.*\b(?:file|document|pdf)s?\b",
        re.IGNORECASE,
    ),
)

NO_ANSWER = (
    "I couldn't find enough information in the uploaded "
    "documents to answer that question."
)


def _is_document_overview_query(query: str) -> bool:
    return any(
        pattern.search(query)
        for pattern in DOCUMENT_OVERVIEW_PATTERNS
    )


def _select_overview_chunks(
    chunks: list[dict],
    limit: int,
) -> list[dict]:
    """Choose passages spread across active documents and their pages."""

    grouped = defaultdict(list)

    for chunk in chunks:
        grouped[chunk["document_id"]].append(chunk)

    documents = list(grouped.values())
    allocations = [0] * len(documents)
    remaining = min(limit, sum(map(len, documents)))

    while remaining:
        allocated_in_round = False

        for index, document_chunks in enumerate(documents):
            if allocations[index] >= len(document_chunks):
                continue

            allocations[index] += 1
            remaining -= 1
            allocated_in_round = True

            if not remaining:
                break

        if not allocated_in_round:
            break

    selected = []

    for document_chunks, count in zip(documents, allocations):
        if count == 1:
            indexes = [0]
        else:
            indexes = [
                round(index * (len(document_chunks) - 1) / (count - 1))
                for index in range(count)
            ]

        selected.extend(
            document_chunks[index]
            for index in indexes
        )

    return selected


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


def _document_overview_sources() -> list[dict]:
    chunks = sqlite_store.get_active_document_chunks()
    selected = _select_overview_chunks(
        chunks,
        settings.rag_max_context_chunks,
    )

    return [
        {
            **chunk,
            "semantic_score": None,
            "relevance_score": None,
        }
        for chunk in selected
    ]


def answer_question(
    query: str,
    top_k: int | None = None,
) -> dict:
    """
    Execute hybrid retrieval and grounded answer generation.
    """

    query = query.strip()

    if not query:
        raise ValueError("The question cannot be empty.")

    overview_query = _is_document_overview_query(query)

    # Broad overview questions need representative passages, not
    # similarity matches to generic words like "file" or "document".
    if overview_query:
        retrieved = _document_overview_sources()
        retrieval_mode = "document_overview"
    else:
        retrieved = hybrid_search(
            query=query,
            top_k=top_k,
        )
        if settings.enable_keyword_search and settings.enable_semantic_search:
            retrieval_mode = "hybrid"
        elif settings.enable_keyword_search:
            retrieval_mode = "keyword"
        else:
            retrieval_mode = "semantic"

    # Handle absent evidence without calling the LLM.
    if not retrieved:
        logger.info(
            "No active document passages found for a query."
        )

        return {
            "query": query,
            "answer": NO_ANSWER,
            "citations": [],
            "not_found": True,
            "retrieval_mode": retrieval_mode,
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
            "retrieval_mode": retrieval_mode,
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
            "retrieval_mode": retrieval_mode,
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

    verified_quotes = {}
    source_content = {
        source["source_ref"]: source["content"]
        for source in context_sources
    }
    for item in generated.get(
        "source_quotes",
        generated.get("citation_quotes", []),
    ):
        if not isinstance(item, dict):
            continue

        source_ref = item.get("source_ref")
        quote = item.get("quote")
        if source_ref not in source_content or not isinstance(quote, str):
            continue

        if quote_matches_source(
            quote,
            source_content[source_ref],
        ):
            verified_quotes[source_ref] = quote.strip()

    cited_refs = set(citations)
    result_sources = [
        {
            **source,
            "quoted_text": verified_quotes.get(
                source["source_ref"]
            ),
        }
        for source in display_sources
    ]
    cited_sources = [
        source
        for source in result_sources
        if source["source_ref"] in cited_refs
    ]
    related_sources = [
        source
        for source in result_sources
        if source["source_ref"] not in cited_refs
    ]
    ordered_sources = (cited_sources + related_sources)[:3]

    logger.info(
        "Generated a grounded answer from %s retrieved sources; "
        "%s were cited.",
        len(display_sources),
        len(citations),
    )

    return {
        "query": query,
        "answer": answer,
        "citations": citations,
        "not_found": False,
        "retrieval_mode": retrieval_mode,
        "results": ordered_sources,
    }