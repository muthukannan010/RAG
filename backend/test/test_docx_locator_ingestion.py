from io import BytesIO

import numpy as np
from docx import Document

from app.core.config import settings
from app.db import sqlite_store, vector_store
from app.services import document_service, ingestion


def _make_docx(paragraph_text):
    document = Document()
    document.add_heading("Locator test", level=1)
    document.add_paragraph(paragraph_text)
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Key"
    table.cell(0, 1).text = "Value"
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _locator_mapping(structural_metadata):
    return next(
        entry["locator_mapping"]
        for entry in structural_metadata
        if entry.get("metadata_type") == "docx_locator_mapping"
    )


def test_docx_replacement_and_deletion_persist_versioned_locators(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "sqlite_db_path",
        tmp_path / "documents.sqlite3",
    )
    monkeypatch.setattr(
        settings,
        "chroma_db_path",
        tmp_path / "chroma",
    )
    monkeypatch.setattr(
        settings,
        "documents_dir",
        tmp_path / "files",
    )
    monkeypatch.setattr(
        ingestion,
        "embed_texts",
        lambda texts: np.tile(
            np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
            (len(texts), 1),
        ),
    )
    sqlite_store.initialize_database()

    uploaded = document_service.add_document(
        "first.docx",
        _make_docx("The copper protocol supports locator persistence."),
    )
    document_id = uploaded["id"]
    first_record = sqlite_store.get_document(document_id)
    first_version = first_record["active_version_id"]

    first_chunks = sqlite_store.get_active_document_chunks()
    assert first_chunks
    first_metadata = first_chunks[0]["structural_metadata"]
    first_mapping = _locator_mapping(first_metadata)
    assert first_mapping["mapping_status"] == "resolved"
    assert first_mapping["document_version_id"] == first_version
    assert any(
        segment["element_type"] == "table_cell_paragraph"
        for segment in first_mapping["locator_segments"]
    )

    keyword_results = sqlite_store.search_active_chunks(
        '"copper"',
        5,
    )
    assert keyword_results[0]["structural_metadata"] == first_metadata
    semantic_results = vector_store.query_chunks(
        query_embedding=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
        active_version_ids=[first_version],
        top_k=5,
    )
    assert semantic_results
    assert semantic_results[0]["structural_metadata"] == first_metadata

    replaced = document_service.replace_document(
        document_id,
        "replacement.docx",
        _make_docx("The glacier protocol creates a new locator version."),
    )
    assert replaced["id"] == document_id
    second_record = sqlite_store.get_document(document_id)
    second_version = second_record["active_version_id"]
    assert second_version != first_version

    second_chunks = sqlite_store.get_active_document_chunks()
    assert second_chunks
    second_metadata = second_chunks[0]["structural_metadata"]
    second_mapping = _locator_mapping(second_metadata)
    assert second_mapping["mapping_status"] == "resolved"
    assert second_mapping["document_version_id"] == second_version
    assert all(
        segment["document_version_id"] == second_version
        for segment in second_mapping["locator_segments"]
    )
    assert all(
        first_mapping != _locator_mapping(
            chunk["structural_metadata"]
        )
        for chunk in second_chunks
    )
    stored = vector_store.get_collection().get(
        include=["metadatas"],
    )
    assert first_version not in {
        metadata["version_id"]
        for metadata in stored["metadatas"]
    }

    document_service.delete_document(document_id)
    assert sqlite_store.get_active_document_chunks() == []
    remaining = vector_store.get_collection().get(
        include=["metadatas"],
    )
    assert second_version not in {
        metadata["version_id"]
        for metadata in remaining["metadatas"]
    }
