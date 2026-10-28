import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.core.config import settings


def _connect():
    settings.sqlite_db_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        settings.sqlite_db_path,
        timeout=30,
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")

    return connection


@contextmanager
def _connection():
    connection = _connect()

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with _connection() as connection:
        connection.execute("PRAGMA journal_mode = WAL")

        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
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

            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                version_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                page_number INTEGER NOT NULL,
                text TEXT NOT NULL,
                bbox_json TEXT NOT NULL,
                FOREIGN KEY(document_id)
                    REFERENCES documents(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS
                idx_chunks_document_version
            ON chunks(document_id, version_id);

            CREATE INDEX IF NOT EXISTS
                idx_documents_status
            ON documents(status);
            """
        )


def _row_to_dict(row):
    return dict(row) if row is not None else None


def get_document(document_id: str):
    with _connection() as connection:
        row = connection.execute(
            "SELECT * FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()

    return _row_to_dict(row)


def list_documents():
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM documents
            ORDER BY updated_at DESC
            """
        ).fetchall()

    return [_row_to_dict(row) for row in rows]


def get_active_version_ids() -> list[str]:
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT active_version_id
            FROM documents
            WHERE status = 'ready'
            """
        ).fetchall()

    return [row["active_version_id"] for row in rows]


def save_document_version(document_record, chunks):
    """
    Insert a document or atomically switch an existing document
    to a newly indexed version.

    The vector records must be written before this function.
    """

    with _connection() as connection:
        old_row = connection.execute(
            "SELECT * FROM documents WHERE id = ?",
            (document_record["id"],),
        ).fetchone()

        old_record = _row_to_dict(old_row)

        if old_record is not None:
            # Do not overwrite a document undergoing deletion.
            if old_record["status"] == "deleting":
                raise RuntimeError(
                    "This document is being deleted."
                )

            connection.execute(
                """
                UPDATE documents
                SET
                    filename = ?,
                    stored_path = ?,
                    size_bytes = ?,
                    page_count = ?,
                    chunk_count = ?,
                    active_version_id = ?,
                    status = 'ready',
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    document_record["filename"],
                    document_record["stored_path"],
                    document_record["size_bytes"],
                    document_record["page_count"],
                    document_record["chunk_count"],
                    document_record["active_version_id"],
                    document_record["updated_at"],
                    document_record["id"],
                ),
            )

            connection.execute(
                "DELETE FROM chunks WHERE document_id = ?",
                (document_record["id"],),
            )

        else:
            connection.execute(
                """
                INSERT INTO documents (
                    id,
                    filename,
                    stored_path,
                    size_bytes,
                    page_count,
                    chunk_count,
                    active_version_id,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)
                """,
                (
                    document_record["id"],
                    document_record["filename"],
                    document_record["stored_path"],
                    document_record["size_bytes"],
                    document_record["page_count"],
                    document_record["chunk_count"],
                    document_record["active_version_id"],
                    document_record["created_at"],
                    document_record["updated_at"],
                ),
            )

        connection.executemany(
            """
            INSERT INTO chunks (
                id,
                document_id,
                version_id,
                chunk_index,
                page_number,
                text,
                bbox_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk["id"],
                    document_record["id"],
                    document_record["active_version_id"],
                    chunk["chunk_index"],
                    chunk["page_number"],
                    chunk["text"],
                    json.dumps(chunk["bbox"]),
                )
                for chunk in chunks
            ],
        )

    return old_record


def mark_document_deleting(document_id: str):
    """
    Make a document ineligible for semantic search before
    removing its vector records and stored file.
    """

    with _connection() as connection:
        connection.execute(
            """
            UPDATE documents
            SET status = 'deleting'
            WHERE id = ?
            """,
            (document_id,),
        )

        row = connection.execute(
            "SELECT * FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()

    record = _row_to_dict(row)

    if record is None:
        raise KeyError(
            f"Document '{document_id}' was not found."
        )

    return record


def delete_document_record(document_id: str) -> None:
    with _connection() as connection:
        connection.execute(
            "DELETE FROM documents WHERE id = ?",
            (document_id,),
        )