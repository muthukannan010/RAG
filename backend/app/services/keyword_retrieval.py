import logging
import re
import unicodedata

from app.core.config import settings
from app.db import sqlite_store


logger = logging.getLogger(__name__)

QUERY_TOKEN_PATTERN = re.compile(
    r"\d+(?:[.,]\d+)*%?|[\w]+(?:['’][\w]+)*",
    re.UNICODE,
)


def _quote_fts_term(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def preprocess_keyword_query(query: str) -> str:
    """Normalize a user query and build a safe FTS5 expression."""

    normalized_query = unicodedata.normalize("NFKC", query)
    normalized_query = " ".join(normalized_query.split())

    if not normalized_query:
        raise ValueError("The search query cannot be empty.")

    phrase_query = (
        len(normalized_query) >= 2
        and normalized_query.startswith('"')
        and normalized_query.endswith('"')
    )
    if phrase_query:
        normalized_query = normalized_query[1:-1].strip()

    terms = QUERY_TOKEN_PATTERN.findall(normalized_query)
    if not terms:
        raise ValueError(
            "The search query must contain at least one searchable term."
        )

    if phrase_query:
        return _quote_fts_term(" ".join(terms))

    quoted_terms = [_quote_fts_term(term) for term in terms]
    if len(quoted_terms) == 1:
        return quoted_terms[0]

    phrase = _quote_fts_term(" ".join(terms))
    all_terms = " AND ".join(quoted_terms)
    return f"({phrase}) OR ({all_terms})"


def keyword_search(
    query: str,
    top_k: int | None = None,
) -> list[dict]:
    normalized_query = unicodedata.normalize("NFKC", query)
    if not normalized_query.strip():
        raise ValueError("The search query cannot be empty.")

    result_limit = (
        settings.keyword_top_k if top_k is None else top_k
    )
    if result_limit <= 0:
        raise ValueError("The result limit must be positive.")

    match_expression = preprocess_keyword_query(query)
    results = sqlite_store.search_active_chunks(
        match_expression,
        result_limit,
    )

    for rank, result in enumerate(results, start=1):
        result["keyword_rank"] = rank

    logger.info(
        "Keyword search returned %s results.",
        len(results),
    )
    return results
