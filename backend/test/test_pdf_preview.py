import uuid

import pymupdf
import pytest

from app.api.routes import documents
from app.models.schema import PDFPagePreviewRequest
from app.services import pdf_preview


def _create_pdf(path):
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text(
            (72, 72),
            "The exact cited passage is visible here.",
        )
        document.save(path)


def test_render_pdf_page_highlights_an_exact_quote(tmp_path):
    path = tmp_path / "source.pdf"
    _create_pdf(path)

    image, matched, highlight_y = pdf_preview.render_pdf_page(
        path,
        1,
        "exact cited passage",
    )

    assert matched is True
    assert 0 <= highlight_y <= 1
    assert image.startswith(b"\x89PNG\r\n\x1a\n")


def test_render_pdf_page_does_not_highlight_unmatched_text(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "source.pdf"
    _create_pdf(path)
    monkeypatch.setattr(
        pdf_preview.pytesseract,
        "image_to_data",
        lambda image, output_type: {
            "text": [],
            "left": [],
            "top": [],
            "width": [],
            "height": [],
        },
    )

    image, matched, highlight_y = pdf_preview.render_pdf_page(
        path,
        1,
        "a quotation that is not on this page",
    )

    assert matched is False
    assert highlight_y is None
    assert image.startswith(b"\x89PNG\r\n\x1a\n")


def test_render_pdf_page_rejects_an_invalid_page(tmp_path):
    path = tmp_path / "source.pdf"
    _create_pdf(path)

    with pytest.raises(ValueError, match="page does not exist"):
        pdf_preview.render_pdf_page(path, 2)


def test_preview_does_not_render_an_unverified_citation(
    tmp_path,
    monkeypatch,
):
    document_id = str(uuid.uuid4())
    path = tmp_path / "source.pdf"
    path.write_bytes(b"test")
    rendered = {}

    def fake_render(pdf_path, page, quote):
        rendered["quote"] = quote
        return b"image", bool(quote), None

    monkeypatch.setattr(
        documents.settings,
        "documents_dir",
        tmp_path,
    )
    monkeypatch.setattr(
        documents.sqlite_store,
        "get_document",
        lambda value: {
            "id": value,
            "status": "ready",
            "page_count": 1,
            "stored_path": str(path),
        },
    )
    monkeypatch.setattr(
        documents.sqlite_store,
        "get_active_chunks_for_page",
        lambda value, page: [
            {"content": "The verified citation is here."}
        ],
    )
    monkeypatch.setattr(
        documents,
        "render_pdf_page",
        fake_render,
    )

    response = documents.get_document_page_preview(
        document_id,
        1,
        PDFPagePreviewRequest(
            quoted_text="An unrelated quote."
        ),
    )

    assert response.media_type == "image/png"
    assert rendered["quote"] is None
    assert response.headers["X-PDF-Highlight-Matched"] == "false"
