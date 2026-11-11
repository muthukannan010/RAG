import re


def quote_matches_source(quote: str, source_text: str) -> bool:
    """Match a quotation while tolerating case and whitespace differences."""

    normalized_quote = " ".join(
        re.sub(r"\s+", " ", quote).casefold().split()
    )
    if not normalized_quote:
        return False

    normalized_source = " ".join(
        re.sub(r"\s+", " ", source_text).casefold().split()
    )
    return normalized_quote in normalized_source
