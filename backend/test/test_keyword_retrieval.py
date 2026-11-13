import sqlite3

import pytest

from app.core.config import settings
from app.db import sqlite_store
from app.services.keyword_retrieval import (
    keyword_search,
    preprocess_keyword_query,
)


@pytest.fixture
def keyword_database(tmp_path, monkeypatch):
    monkeypatch.setattr(
        settings,
        "sqlite_db_path",
        tmp_path / "keyword-test.sqlite3",
    )
    sqlite_store.initialize_database()


def _save_version(
    version_id: str,
    chunks: list[dict],
    document_id: str = "document-1",
    filename: str = "sample.pdf",
) -> None:
    sqlite_store.save_document_version(
        {
            "id": document_id,
            "filename": filename,
            "stored_path": filename,
            "size_bytes": 1,
            "page_count": 1,
            "chunk_count": len(chunks),
            "active_version_id": version_id,
            "status": "ready",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
        [
            {
                "chunk_index": index,
                "page_number": 1,
                "bbox": [],
                **chunk,
            }
            for index, chunk in enumerate(chunks)
        ],
    )


def test_page_lookup_returns_only_active_chunks_across_documents(
    keyword_database,
):
    _save_version(
        "version-1",
        [{"id": "first-page-20", "page_number": 20, "text": "first"}],
        document_id="document-1",
        filename="first.pdf",
    )
    _save_version(
        "version-2",
        [{"id": "second-page-20", "page_number": 20, "text": "second"}],
        document_id="document-2",
        filename="second.pdf",
    )

    initial_results = sqlite_store.get_active_chunks_for_page_number(20)
    assert {item["chunk_id"] for item in initial_results} == {
        "first-page-20",
        "second-page-20",
    }

    _save_version(
        "version-3",
        [{"id": "first-page-21", "page_number": 21, "text": "updated"}],
        document_id="document-1",
        filename="first.pdf",
    )

    page_20_results = sqlite_store.get_active_chunks_for_page_number(20)
    assert [item["chunk_id"] for item in page_20_results] == [
        "second-page-20"
    ]


def test_keyword_query_normalizes_and_preserves_numbers():
    expression = preprocess_keyword_query(
        "  Alpha731   73.5% "
    )

    assert '"Alpha731"' in expression
    assert '"73.5%"' in expression


def test_keyword_search_supports_exact_phrase_and_active_versions(
    keyword_database,
):
    _save_version(
        "version-1",
        [
            {
                "id": "chunk-1",
                "text": "The alpha731 recovery procedure is documented.",
            },
            {
                "id": "chunk-2",
                "text": "The procedure describes recovery for alpha731.",
            },
        ],
    )

    results = keyword_search('"alpha731 recovery"')

    assert [result["chunk_id"] for result in results] == ["chunk-1"]
    assert results[0]["keyword_rank"] == 1
    assert results[0]["version_id"] == "version-1"


def test_keyword_index_tracks_replacement_and_deletion(
    keyword_database,
):
    _save_version(
        "version-1",
        [{"id": "old-chunk", "text": "obsolete moonstone procedure"}],
    )
    assert keyword_search("moonstone")

    _save_version(
        "version-2",
        [{"id": "new-chunk", "text": "current glacier procedure"}],
    )
    assert keyword_search("moonstone") == []
    assert [
        result["chunk_id"]
        for result in keyword_search("glacier")
    ] == ["new-chunk"]

    sqlite_store.mark_document_deleting("document-1")
    assert keyword_search("glacier") == []
    sqlite_store.delete_document_record("document-1")
    assert keyword_search("glacier") == []


def test_initialize_backfills_existing_chunk_rows(tmp_path, monkeypatch):
    database_path = tmp_path / "existing.sqlite3"
    monkeypatch.setattr(
        settings,
        "sqlite_db_path",
        database_path,
    )

    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                page_count INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL,
                active_version_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE chunks (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                version_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                page_number INTEGER NOT NULL,
                text TEXT NOT NULL,
                bbox_json TEXT NOT NULL
            );
            INSERT INTO documents VALUES (
                'document-1', 'sample.pdf', 'sample.pdf', 1, 1, 1,
                'version-1', 'ready', 'now', 'now'
            );
            INSERT INTO chunks VALUES (
                'chunk-1', 'document-1', 'version-1', 0, 1,
                'preexisting exact keyword', '[]'
            );
            """
        )

    sqlite_store.initialize_database()

    assert [
        result["chunk_id"]
        for result in keyword_search("preexisting")
    ] == ["chunk-1"]


def test_keyword_search_rejects_empty_or_nonsearchable_queries():
    with pytest.raises(ValueError):
        preprocess_keyword_query("   ")

    with pytest.raises(ValueError):
        keyword_search("!!!")


def test_keyword_query_escapes_fts_operators_and_punctuation(
    keyword_database,
):
    results = keyword_search('alpha") OR *--')

    assert results == []
