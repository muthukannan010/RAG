import logging

from app.core.config import settings
from app.services.chunker import chunk_pages
from app.services.embedding import embed_texts
from app.services.pdf_processor import extract_pdf_pages


logger = logging.getLogger(__name__)


def prepare_document(pdf_bytes: bytes):
    """
    Convert PDF bytes into pages, chunks and embeddings.

    Returns a prepared package for the document service
    to store and index.
    """

    if not pdf_bytes:
        raise ValueError("The uploaded PDF is empty.")

    pages = extract_pdf_pages(pdf_bytes)

    chunks = chunk_pages(
        pages,
        chunk_size=settings.chunk_size_chars,
        chunk_overlap=settings.chunk_overlap_chars,
    )

    if not chunks:
        raise ValueError(
            "No extractable text was found in this PDF. "
            "Image-only scanned PDFs require OCR."
        )

    logger.info(
        "Prepared PDF: %s pages, %s chunks.",
        len(pages),
        len(chunks),
    )

    embeddings = embed_texts(
        [chunk["text"] for chunk in chunks]
    )

    if len(embeddings) != len(chunks):
        raise RuntimeError(
            "Embedding generation returned an unexpected number "
            "of vectors."
        )

    return {
        "page_count": len(pages),
        "chunks": chunks,
        "embeddings": embeddings,
    }