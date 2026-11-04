import logging
import re
from time import perf_counter

from app.core.config import settings
from app.services.keyword_retrieval import keyword_search
from app.services.retrieval import semantic_search


logger = logging.getLogger(__name__)


def hybrid_search(
    query: str,
    top_k: int | None = None,
) -> list[dict]:
    """Combine keyword and semantic candidates using weighted RRF."""

    hybrid_started = perf_counter()
    query = query.strip()
    if not query:
        raise ValueError("The search query cannot be empty.")

    logger.info(
        "Hybrid retrieval received a query of %s characters.",
        len(query),
    )

    result_limit = settings.hybrid_top_k if top_k is None else top_k
    if result_limit <= 0:
        raise ValueError("The result limit must be positive.")

    keyword_results = []
    semantic_results = []

    if settings.enable_keyword_search:
        candidate_k = max(
            settings.keyword_top_k,
            result_limit * 4,
        )
        started = perf_counter()
        try:
            keyword_results = keyword_search(
                query,
                top_k=candidate_k,
            )
        except Exception:
            logger.exception(
                "Keyword retrieval failed; hybrid search stopped "
                "after %.3f seconds.",
                perf_counter() - hybrid_started,
            )
            raise
        finally:
            logger.info(
                "Keyword retrieval took %.3f seconds.",
                perf_counter() - started,
            )

    if settings.enable_semantic_search:
        candidate_k = max(
            settings.semantic_top_k,
            result_limit * 4,
        )
        started = perf_counter()
        try:
            semantic_results = semantic_search(
                query,
                top_k=candidate_k,
            )
        except Exception:
            logger.exception(
                "Semantic retrieval failed; hybrid search stopped "
                "after %.3f seconds.",
                perf_counter() - hybrid_started,
            )
            raise
        finally:
            logger.info(
                "Semantic retrieval took %.3f seconds.",
                perf_counter() - started,
            )

    logger.info(
        "Hybrid retrieval started for a query of %s characters; "
        "keyword candidates=%s, semantic candidates=%s.",
        len(query),
        len(keyword_results),
        len(semantic_results),
    )

    merged = {}
    keyword_ranks = {}
    semantic_ranks = {}

    for rank, result in enumerate(keyword_results, start=1):
        chunk_id = result["chunk_id"]
        if chunk_id not in keyword_ranks:
            keyword_ranks[chunk_id] = rank
            merged[chunk_id] = dict(result)

    for rank, result in enumerate(semantic_results, start=1):
        chunk_id = result["chunk_id"]
        if chunk_id not in semantic_ranks:
            semantic_ranks[chunk_id] = rank
        if chunk_id in merged:
            if rank == semantic_ranks[chunk_id]:
                merged[chunk_id].update(result)
        else:
            merged[chunk_id] = dict(result)

    candidate_count = len(keyword_results) + len(semantic_results)
    ranked_results = []
    for chunk_id, result in merged.items():
        keyword_rank = keyword_ranks.get(chunk_id)
        semantic_rank = semantic_ranks.get(chunk_id)

        hybrid_score = 0.0
        if keyword_rank is not None:
            hybrid_score += settings.keyword_weight / (
                settings.rrf_k + keyword_rank
            )
        if semantic_rank is not None:
            hybrid_score += settings.semantic_weight / (
                settings.rrf_k + semantic_rank
            )

        result.update(
            {
                "keyword_rank": keyword_rank,
                "semantic_rank": semantic_rank,
                "hybrid_score": hybrid_score,
            }
        )
        ranked_results.append(result)

    ranked_results.sort(
        key=lambda result: (
            -result["hybrid_score"],
            result["semantic_rank"] or float("inf"),
            result["keyword_rank"] or float("inf"),
            result["chunk_id"],
        )
    )

    merged_count = len(ranked_results)
    if settings.remove_duplicate_chunks:
        seen_content = set()
        unique_results = []
        for result in ranked_results:
            normalized_text = " ".join(
                re.findall(
                    r"\w+",
                    result["content"].casefold(),
                    flags=re.UNICODE,
                )
            )
            content_key = (
                result["document_id"],
                result["page_number"],
                normalized_text,
            )
            if content_key in seen_content:
                continue
            seen_content.add(content_key)
            unique_results.append(result)
        ranked_results = unique_results

    final_results = ranked_results[:result_limit]
    logger.info(
        "Hybrid retrieval considered %s candidates, merged %s unique "
        "chunk IDs, removed %s duplicate IDs and %s duplicate texts, "
        "returned %s results in %.3f seconds.",
        candidate_count,
        len(merged),
        candidate_count - len(merged),
        merged_count - len(ranked_results),
        len(final_results),
        perf_counter() - hybrid_started,
    )
    return final_results
