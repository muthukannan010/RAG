from io import BytesIO

from docx import Document

from app.services.chunker import chunk_pages
from app.services import ingestion
from app.services.ingestion import extract_document_pages


def _make_docx() -> bytes:
    document = Document()
    document.add_heading("Overview", level=1)
    document.add_paragraph("Intro paragraph.")
    document.add_heading("Details", level=2)
    document.add_paragraph("Detail paragraph with useful information.")

    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Key"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "Mode"
    table.cell(1, 1).text = "Local"

    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _extract_sample_docx():
    return extract_document_pages(
        _make_docx(),
        filename="sample.docx",
    )


def test_docx_headings_and_paragraphs_keep_separate_metadata():
    pages = _extract_sample_docx()
    blocks = pages[0]["blocks"]

    overview = next(
        block
        for block in blocks
        if block["text"] == "Overview"
    )
    intro = next(
        block
        for block in blocks
        if block["text"] == "Intro paragraph."
    )
    details = next(
        block
        for block in blocks
        if block["text"] == "Details"
    )
    paragraph = next(
        block
        for block in blocks
        if block["text"] == "Detail paragraph with useful information."
    )

    assert overview["metadata"]["element_type"] == "Title"
    assert overview["metadata"]["element_index"] == 0
    assert overview["metadata"]["element_id"]
    assert overview["metadata"]["section_path"] == ["Overview"]
    assert intro["metadata"]["section_path"] == ["Overview"]
    assert details["metadata"]["section_path"] == [
        "Overview",
        "Details",
    ]
    assert details["metadata"]["heading_level"] == 2
    assert paragraph["metadata"]["section_path"] == [
        "Overview",
        "Details",
    ]
    assert paragraph["metadata"]["element_index"] > (
        details["metadata"]["element_index"]
    )
    assert not any(
        label in block["text"]
        for block in blocks
        for label in ("Source:", "Element:", "Section:")
    )


def test_one_chunk_preserves_all_contributing_docx_elements():
    pages = _extract_sample_docx()

    chunks = chunk_pages(
        pages,
        chunk_size=1000,
        chunk_overlap=100,
    )

    assert len(chunks) == 1
    provenance = chunks[0]["provenance"]
    assert len(provenance) == len(pages[0]["blocks"])
    assert {item["element_type"] for item in provenance} >= {
        "Title",
        "Table",
    }
    assert any(
        item["section_path"] == ["Overview", "Details"]
        for item in provenance
    )


def test_large_docx_element_keeps_provenance_and_text_ranges():
    text = "A long sentence with useful content. " * 20
    pages = [
        {
            "page_number": 1,
            "blocks": [
                {
                    "text": text,
                    "bbox": [],
                    "metadata": {
                        "format": "docx",
                        "element_type": "Paragraph",
                        "element_index": 3,
                        "element_id": "paragraph-3",
                        "section_path": ["Details"],
                        "original_text": text,
                    },
                }
            ],
        }
    ]

    chunks = chunk_pages(
        pages,
        chunk_size=100,
        chunk_overlap=20,
    )

    assert len(chunks) > 1
    for chunk in chunks:
        source = chunk["provenance"][0]
        start = source["text_range"]["start"]
        end = source["text_range"]["end"]
        assert source["element_id"] == "paragraph-3"
        assert source["section_path"] == ["Details"]
        assert chunk["text"] == text[start:end]


def test_docx_table_keeps_identity_position_and_readable_text():
    pages = _extract_sample_docx()
    table = next(
        block
        for block in pages[0]["blocks"]
        if block["metadata"]["element_type"] == "Table"
    )

    assert "Key | Value" in table["text"]
    assert "Mode | Local" in table["text"]
    assert table["metadata"]["table_index"] == 0
    assert table["metadata"]["table_position"] == (
        table["metadata"]["element_index"]
    )
    assert table["metadata"]["element_id"]
    assert table["metadata"]["original_text"]
    assert "<table>" in table["metadata"]["table_html"]


def test_prepare_docx_attaches_versioned_locator_metadata(monkeypatch):
    monkeypatch.setattr(
        ingestion,
        "embed_texts",
        lambda texts: [[0.0] for _ in texts],
    )

    prepared = ingestion.prepare_document(
        _make_docx(),
        filename="sample.docx",
        document_version_id="version-1",
    )

    assert len(prepared["chunks"]) == 1
    chunk = prepared["chunks"][0]
    metadata = chunk["provenance"]
    locator_record = metadata[-1]
    mapping = locator_record["locator_mapping"]

    assert locator_record["metadata_type"] == "docx_locator_mapping"
    assert mapping["mapping_status"] == "resolved"
    assert mapping["document_version_id"] == "version-1"
    assert "original_chunk_text" not in mapping
    assert chunk["text"]
    assert all(
        segment["document_version_id"] == "version-1"
        for segment in mapping["locator_segments"]
    )
    assert any(
        segment["element_type"] == "table_cell_paragraph"
        for segment in mapping["locator_segments"]
    )
    assert {item["element_type"] for item in metadata[:-1]} >= {
        "Title",
        "Table",
    }


def test_docx_locator_failure_does_not_fail_ingestion(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(
        ingestion,
        "embed_texts",
        lambda texts: [[0.0] for _ in texts],
    )

    def fail_index(_document_bytes):
        raise ValueError("synthetic locator failure")

    monkeypatch.setattr(
        ingestion,
        "build_docx_ooxml_index",
        fail_index,
    )

    prepared = ingestion.prepare_document(
        _make_docx(),
        filename="sample.docx",
        document_version_id="version-1",
    )

    assert prepared["chunks"]
    mapping = prepared["chunks"][0]["provenance"][-1][
        "locator_mapping"
    ]
    assert mapping["mapping_status"] == "unresolved"
    assert mapping["locator_segments"] == []
    assert "continuing ingestion" in caplog.text
