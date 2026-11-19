import json
import logging
import re
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any

from unstructured.partition.auto import partition
from unstructured.partition.text import partition_text

from app.core.config import settings
from app.services.chunker import chunk_pages
from app.services.embedding import embed_texts
from app.services.pdf_processor import extract_pdf_pages


logger = logging.getLogger(__name__)

SUPPORTED_DOCUMENT_FORMATS = {
    ".docx",
    ".pptx",
    ".xlsx",
    ".txt",
    ".csv",
    ".md",
    ".html",
    ".htm",
    ".json",
    ".xml",
}


class _TableTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(
        self,
        tag: str,
        _attrs: list[tuple[str, str | None]],
    ):
        del _attrs
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"}:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data: str):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str):
        if tag in {"td", "th"} and self._cell is not None:
            cell = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            if self._row is not None:
                self._row.append(cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None


def _safe_filename(filename: str) -> str:
    return filename.replace("\\", "/").rsplit("/", 1)[-1].strip()


def _is_pdf_document(document_bytes: bytes, filename: str | None) -> bool:
    extension = Path(filename).suffix.lower() if filename else ""
    return (
        extension == ".pdf"
        or b"%PDF-" in document_bytes[:1024]
        or filename is None
    )


def _readable_table(element) -> str:
    metadata = getattr(element, "metadata", None)
    table_html = getattr(metadata, "text_as_html", None)
    if not table_html:
        return ""

    parser = _TableTextParser()
    parser.feed(str(table_html))
    return "\n".join(
        " | ".join(cell for cell in row if cell)
        for row in parser.rows
    )


def _element_text(element) -> str:
    text = str(getattr(element, "text", "") or "").strip()
    if str(getattr(element, "category", "")).lower() == "table":
        return _readable_table(element) or text
    return text


def _page_number(metadata) -> int | None:
    value = getattr(metadata, "page_number", None)
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _normalize_unstructured_elements(
    elements,
    filename: str,
    extension: str,
) -> list[dict[str, Any]]:
    title_by_id = {}
    for element in elements:
        category = str(
            getattr(element, "category", type(element).__name__)
        ).lower()
        element_text = _element_text(element)
        element_id = getattr(element, "id", None)
        if (
            element_id
            and category in {"title", "header"}
            and element_text
        ):
            title_by_id[element_id] = element_text

    pages_by_key = {}
    pages = []
    current_section = None

    for element in elements:
        metadata = getattr(element, "metadata", None)
        category = str(
            getattr(element, "category", type(element).__name__)
        )
        category_key = category.lower()
        text = _element_text(element)
        if not text:
            continue

        if category_key in {"title", "header"}:
            current_section = text

        parent_id = getattr(metadata, "parent_id", None)
        section = title_by_id.get(parent_id) or current_section

        raw_page_number = _page_number(metadata)
        raw_page_name = getattr(metadata, "page_name", None)
        page_name = str(raw_page_name).strip() if raw_page_name else None

        if extension == ".xlsx" and page_name:
            page_key = ("sheet", page_name)
        elif raw_page_number is not None:
            page_key = ("page", raw_page_number)
        else:
            page_key = ("document", 1)

        if page_key not in pages_by_key:
            if page_key[0] == "sheet":
                normalized_page_number = len(pages) + 1
            else:
                normalized_page_number = raw_page_number or 1

            page = {
                "page_number": normalized_page_number,
                "blocks": [],
            }
            pages_by_key[page_key] = page
            pages.append(page)
        else:
            page = pages_by_key[page_key]

        context = [
            f"Source: {filename}",
            f"Element: {category}",
        ]
        if extension == ".pptx":
            context.append(
                f"Slide: {raw_page_number or page['page_number']}"
            )
        elif extension == ".xlsx":
            if page_name:
                context.append(f"Sheet: {page_name}")
        elif raw_page_number is not None:
            context.append(f"Page: {raw_page_number}")

        if section:
            context.append(f"Section: {section}")

        page["blocks"].append(
            {
                "text": f"[{' | '.join(context)}]\n{text}",
                "bbox": [],
            }
        )

    return [
        page
        for page in pages
        if any(block["text"].strip() for block in page["blocks"])
    ]


def _extract_unstructured_pages(
    document_bytes: bytes,
    filename: str,
    extension: str,
) -> list[dict[str, Any]]:
    try:
        if extension == ".json":
            try:
                json_value = json.loads(document_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"'{filename}' does not contain valid JSON."
                ) from exc

            elements = partition_text(
                text=json.dumps(
                    json_value,
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            elements = partition(
                file=BytesIO(document_bytes),
                metadata_filename=filename,
            )
    except ValueError:
        raise
    except Exception as exc:
        logger.exception(
            "Unstructured extraction failed for %s.",
            filename,
        )
        raise ValueError(
            f"Could not extract text from '{filename}'."
        ) from exc

    pages = _normalize_unstructured_elements(
        elements,
        filename,
        extension,
    )
    if not pages:
        raise ValueError(
            f"No extractable text was found in '{filename}'."
        )

    return pages


def extract_document_pages(
    document_bytes: bytes,
    filename: str | None = None,
) -> list[dict[str, Any]]:
    """Extract a document into the page/block structure used by chunk_pages."""

    if not document_bytes:
        raise ValueError("The uploaded document is empty.")

    if _is_pdf_document(document_bytes, filename):
        return extract_pdf_pages(document_bytes)

    if not filename:
        raise ValueError(
            "A filename is required to identify a non-PDF document format."
        )

    safe_filename = _safe_filename(filename)
    extension = Path(safe_filename).suffix.lower()
    if extension not in SUPPORTED_DOCUMENT_FORMATS:
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_FORMATS))
        raise ValueError(
            f"Unsupported document format '{extension or 'unknown'}'. "
            f"Supported formats: {supported}."
        )

    return _extract_unstructured_pages(
        document_bytes,
        safe_filename,
        extension,
    )


def prepare_document(
    pdf_bytes: bytes,
    filename: str | None = None,
) -> dict[str, Any]:
    """
    Convert a document into pages, chunks and embeddings.

    Returns a prepared package for the document service
    to store and index.
    """

    if not pdf_bytes:
        if filename is None or _is_pdf_document(pdf_bytes, filename):
            raise ValueError("The uploaded PDF is empty.")
        raise ValueError("The uploaded document is empty.")

    is_pdf = _is_pdf_document(pdf_bytes, filename)
    pages = extract_document_pages(pdf_bytes, filename)

    chunks = chunk_pages(
        pages,
        chunk_size=settings.chunk_size_chars,
        chunk_overlap=settings.chunk_overlap_chars,
    )

    if not chunks:
        if is_pdf:
            raise ValueError(
                "No extractable text was found in this PDF. "
                "Image-only scanned PDFs require OCR."
            )
        raise ValueError("No extractable text was found in this document.")

    if is_pdf:
        logger.info(
            "Prepared PDF: %s pages, %s chunks.",
            len(pages),
            len(chunks),
        )
    else:
        logger.info(
            "Prepared %s: %s pages, %s chunks.",
            filename,
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
