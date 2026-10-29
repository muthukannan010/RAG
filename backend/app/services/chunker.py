import re
import uuid

from app.core.config import settings


SENTENCE_BOUNDARIES = (".", "?", "!", "\n", ";")


def _build_page_text(blocks):
    """
    Combine blocks into one page string while tracking the
    original coordinate range of every block.
    """

    pieces = []
    ranges = []
    cursor = 0

    for block in blocks:
        text = block["text"].strip()

        if not text:
            continue

        if pieces:
            pieces.append("\n")
            cursor += 1

        start = cursor
        pieces.append(text)
        cursor += len(text)

        ranges.append(
            {
                "start": start,
                "end": cursor,
                "bbox": block["bbox"],
            }
        )

    return "".join(pieces), ranges


def _choose_chunk_end(text, start, desired_end):
    """
    Prefer a nearby sentence or paragraph boundary while
    keeping the chunk below the configured target size.
    """

    if desired_end >= len(text):
        return len(text)

    lower_bound = start + int(
        (desired_end - start) * 0.60
    )

    best = -1

    for boundary in SENTENCE_BOUNDARIES:
        position = text.rfind(
            boundary,
            lower_bound,
            desired_end,
        )

        best = max(best, position)

    if best >= lower_bound:
        return best + 1

    return desired_end


def chunk_pages(
    pages,
    chunk_size=None,
    chunk_overlap=None,
):
    """
    Split extracted PDF text into page-aware overlapping chunks.

    Each returned chunk includes a stable ID, page number,
    text, chunk index, and relevant bounding boxes.
    """

    size = chunk_size or settings.chunk_size_chars
    overlap = (
        settings.chunk_overlap_chars
        if chunk_overlap is None
        else chunk_overlap
    )

    if size <= 0:
        raise ValueError("Chunk size must be positive.")

    if not 0 <= overlap < size:
        raise ValueError(
            "Chunk overlap must be smaller than chunk size."
        )

    output = []
    global_chunk_index = 0

    for page in pages:
        page_number = page["page_number"]

        page_text, block_ranges = _build_page_text(
            page["blocks"]
        )

        if not page_text.strip():
            continue

        start = 0

        while start < len(page_text):
            desired_end = min(
                start + size,
                len(page_text),
            )

            end = _choose_chunk_end(
                page_text,
                start,
                desired_end,
            )

            text = page_text[start:end].strip()

            if text:
                boxes = [
                    entry["bbox"]
                    for entry in block_ranges
                    if (
                        entry["start"] < end
                        and entry["end"] > start
                    )
                ]

                output.append(
                    {
                        "id": str(uuid.uuid4()),
                        "chunk_index": global_chunk_index,
                        "page_number": page_number,
                        "text": text,
                        "bbox": boxes,
                    }
                )

                global_chunk_index += 1

            if end >= len(page_text):
                break

            next_start = max(
                start + 1,
                end - overlap,
            )

            # Avoid repeatedly producing the same window.
            start = next_start

    return output