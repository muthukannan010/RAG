import logging

from app.core.config import settings
from app.db import sqlite_store, vector_store
from app.services.embedding import embed_query


logger = logging.getLogger(__name__)


def semantic_search(
    query: str,
    top_k: int | None = None,
) -> list[dict]:
    """
    Retrieve the most relevant active PDF chunks using
    semantic vector similarity only.
    """

    query = query.strip()

    if not query:
        raise ValueError("The search query cannot be empty.")

    result_limit = top_k or settings.semantic_top_k

    active_versions = (
        sqlite_store.get_active_version_ids()
    )

    if not active_versions:
        return []

    # Represent the user's question in the embedding space.
    query_embedding = embed_query(query)

    # Retrieve candidates only from currently active versions.
    candidates = vector_store.query_chunks(
        query_embedding=query_embedding,
        active_version_ids=active_versions,
        top_k=result_limit,
    )

    # Filter low similarity results to help return an empty result
    # when there is no sufficiently relevant evidence.
    relevant = [
        item
        for item in candidates
        if item["semantic_score"]
        >= settings.min_semantic_score
    ]

    for item in relevant:
        item["relevance_score"] = item["semantic_score"]

    logger.info(
        "Semantic search returned %s results.",
        len(relevant),
    )

    return relevant