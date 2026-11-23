import json
import sqlite3

import numpy as np

from app.core.config import settings
from app.db import sqlite_store, vector_store


def _document_record(
    document_id="doc-1",
    version_id="version-1",
    chunk_count=1,
):
    return {
        "id": document_id,
        "filename": "sample.docx",
        "stored_path": "sample.docx",
        "size_bytes": 1,
        "page_count": 1,
        "chunk_count": chunk_count,
        "active_version_id": version_id,
        "status": "ready",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }


def _chunk(chunk_id="chunk-1", provenance=None):
    chunk = {
        "id": chunk_id,
        "chunk_index": 0,
        "page_number": 1,
        "text": "Structural metadata retrieval example.",
        "bbox": [],
    }
    if provenance is not None:
        chunk["provenance"] = provenance
    return chunk


def _locator_metadata_record(version_id):
    return {
        "metadata_type": "docx_locator_mapping",
        "locator_mapping": {
            "chunk_id": "chunk-1",
            "document_version_id": version_id,
            "mapping_status": "resolved",
            "locator_segments": [
                {
                    "document_version_id": version_id,
                    "element_type": "paragraph",
                    "structural_path": [
                        {"kind": "paragraph", "index": 0}
                    ],
                    "paragraph_index": 0,
                    "text_range": {"start": 0, "end": 10},
                    "section_path": ["Overview"],
                    "mapping_status": "resolved",
                }
            ],
            "diagnostics": [],
        },
    }


def test_new_database_has_structural_metadata_column(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "new.sqlite3"
    monkeypatch.setattr(settings, "sqlite_db_path", database_path)

    sqlite_store.initialize_database()

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(chunks)"
            )
        }

    assert "structural_metadata_json" in columns


def test_sqlite_round_trips_docx_structural_metadata(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "sqlite_db_path",
        tmp_path / "metadata.sqlite3",
    )
    sqlite_store.initialize_database()
    provenance = [
        {
            "format": "docx",
            "element_type": "Title",
            "element_index": 0,
            "element_id": "title-0",
            "section_path": ["Overview"],
            "original_text": "Overview",
            "text_range": {"start": 0, "end": 8},
        },
        {
            "format": "docx",
            "element_type": "UncategorizedText",
            "element_index": 1,
            "element_id": "paragraph-1",
            "section_path": ["Overview"],
            "original_text": "Structural metadata retrieval example.",
            "text_range": {"start": 0, "end": 39},
        },
    ]
    provenance.append(_locator_metadata_record("version-1"))
    sqlite_store.save_document_version(
        _document_record(),
        [_chunk(provenance=provenance)],
    )

    active_chunks = sqlite_store.get_active_document_chunks()
    assert active_chunks[0]["structural_metadata"] == provenance

    keyword_chunks = sqlite_store.search_active_chunks(
        '"structural"',
        5,
    )
    assert keyword_chunks[0]["structural_metadata"] == provenance
    persisted_mapping = keyword_chunks[0]["structural_metadata"][-1][
        "locator_mapping"
    ]
    assert persisted_mapping["document_version_id"] == "version-1"
    assert persisted_mapping["locator_segments"][0][
        "document_version_id"
    ] == "version-1"

    with sqlite3.connect(settings.sqlite_db_path) as connection:
        saved_json = connection.execute(
            """
            SELECT structural_metadata_json
            FROM chunks
            WHERE id = 'chunk-1'
            """
        ).fetchone()[0]
    assert json.loads(saved_json) == provenance


def test_sqlite_metadata_is_optional_and_replacement_deletes_old_chunks(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "sqlite_db_path",
        tmp_path / "replacement.sqlite3",
    )
    sqlite_store.initialize_database()
    old_provenance = [
        {"element_type": "Title"},
        _locator_metadata_record("version-1"),
    ]
    sqlite_store.save_document_version(
        _document_record(),
        [_chunk(provenance=old_provenance)],
    )

    replacement = _chunk("chunk-2")
    sqlite_store.save_document_version(
        _document_record(version_id="version-2"),
        [replacement],
    )

    active_chunks = sqlite_store.get_active_document_chunks()
    assert [item["chunk_id"] for item in active_chunks] == ["chunk-2"]
    assert active_chunks[0]["structural_metadata"] is None
    assert sqlite_store.search_active_chunks(
        '"Structural"',
        5,
    )[0]["structural_metadata"] is None

    sqlite_store.mark_document_deleting("doc-1")
    sqlite_store.delete_document_record("doc-1")
    assert sqlite_store.get_active_document_chunks() == []


def test_chroma_round_trips_metadata_and_keeps_pdf_metadata_optional(
    tmp_path,
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(
        settings,
        "chroma_db_path",
        tmp_path / "chroma",
    )
    provenance = [
        {
            "format": "docx",
            "element_type": "Table",
            "table_index": 0,
            "section_path": ["Details"],
            "text_range": {"start": 0, "end": 15},
        },
        _locator_metadata_record("docx-version"),
    ]
    chunks = [
        _chunk("docx-chunk", provenance),
        _chunk("pdf-chunk"),
    ]
    chunks[1]["text"] = "PDF chunks remain valid without provenance."
    embeddings = np.array(
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        dtype=np.float32,
    )

    vector_store.upsert_chunks(
        document_id="doc-1",
        version_id="docx-version",
        filename="sample.docx",
        chunks=[chunks[0]],
        embeddings=embeddings[:1],
    )
    vector_store.upsert_chunks(
        document_id="doc-2",
        version_id="pdf-version",
        filename="sample.pdf",
        chunks=[chunks[1]],
        embeddings=embeddings[1:],
    )

    results = vector_store.query_chunks(
        query_embedding=embeddings[0],
        active_version_ids=["docx-version", "pdf-version"],
        top_k=2,
    )
    results_by_id = {item["chunk_id"]: item for item in results}

    assert results_by_id["docx-chunk"]["structural_metadata"] == provenance
    assert results_by_id["pdf-chunk"]["structural_metadata"] is None

    vector_store._client = None
    vector_store._collection = None
    vector_store._collection_path = None
    reopened_results = vector_store.query_chunks(
        query_embedding=embeddings[0],
        active_version_ids=["docx-version"],
        top_k=1,
    )
    assert reopened_results[0]["structural_metadata"] == provenance

    stored = vector_store.get_collection().get(
        ids=["docx-chunk", "pdf-chunk"],
        include=["metadatas"],
    )
    stored_by_id = dict(zip(stored["ids"], stored["metadatas"]))
    assert json.loads(
        stored_by_id["docx-chunk"]["structural_metadata_json"]
    ) == provenance
    assert "structural_metadata_json" not in stored_by_id["pdf-chunk"]

    vector_store.get_collection().update(
        ids=["docx-chunk"],
        metadatas=[
            {
                **stored_by_id["docx-chunk"],
                "structural_metadata_json": "{invalid-json",
            }
        ],
    )
    invalid_metadata_results = vector_store.query_chunks(
        query_embedding=embeddings[0],
        active_version_ids=["docx-version"],
        top_k=1,
    )
    assert invalid_metadata_results[0]["structural_metadata"] is None
    assert "invalid structural metadata JSON" in caplog.text

    vector_store.delete_version("docx-version")
    remaining = vector_store.get_collection().get(
        include=["metadatas"],
    )
    assert [metadata["version_id"] for metadata in remaining["metadatas"]] == [
        "pdf-version"
    ]
