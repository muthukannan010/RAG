import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.db import sqlite_store, vector_store
from app.services.ingestion import prepare_document


logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(filename: str) -> str:
    # Never use the user-provided filename as the storage path.
    name = filename.replace("\\", "/").split("/")[-1].strip()

    if not name:
        raise ValueError("The uploaded file needs a filename.")

    if not name.lower().endswith(".pdf"):
        raise ValueError("Only PDF documents are supported.")

    return name


def _public_document(record: dict) -> dict:
    """Return display-safe fields, excluding internal storage paths."""

    return {
        "id": record["id"],
        "filename": record["filename"],
        "size_bytes": record["size_bytes"],
        "page_count": record["page_count"],
        "chunk_count": record["chunk_count"],
        "status": record["status"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
    }


def list_documents() -> list[dict]:
    return [
        _public_document(record)
        for record in sqlite_store.list_documents()
    ]


def get_document_record(document_id: str):
    """Return an internal record for authorized local operations."""

    return sqlite_store.get_document(document_id)


def _remove_file(path: str | Path | None) -> None:
    if not path:
        return

    file_path = Path(path)
    file_path.unlink(missing_ok=True)

    try:
        file_path.parent.rmdir()
    except OSError:
        # The directory may still contain another version.
        pass


def _store_version(
    document_id: str,
    filename: str,
    pdf_bytes: bytes,
    previous_record: dict | None,
) -> dict:
    if len(pdf_bytes) > settings.max_upload_mb * 1024 * 1024:
        raise ValueError(
            f"The maximum upload size is "
            f"{settings.max_upload_mb} MB."
        )

    # Extract text, create chunks and generate embeddings before
    # activating the new version.
    prepared = prepare_document(pdf_bytes)

    version_id = str(uuid.uuid4())

    version_directory = (
        settings.documents_dir / document_id
    )

    version_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    stored_path = (
        version_directory / f"{version_id}.pdf"
    )

    record = {
        "id": document_id,
        "filename": filename,
        "stored_path": str(stored_path.resolve()),
        "size_bytes": len(pdf_bytes),
        "page_count": prepared["page_count"],
        "chunk_count": len(prepared["chunks"]),
        "active_version_id": version_id,
        "status": "ready",
        "created_at": (
            previous_record["created_at"]
            if previous_record
            else _now()
        ),
        "updated_at": _now(),
    }

    # Write to a unique version path. Never overwrite the old PDF
    # before extraction and embedding generation have succeeded.
    stored_path.write_bytes(pdf_bytes)

    try:
        vector_store.upsert_chunks(
            document_id=document_id,
            version_id=version_id,
            filename=filename,
            chunks=prepared["chunks"],
            embeddings=prepared["embeddings"],
        )
    except Exception:
        logger.exception(
            "Vector indexing failed for document %s.",
            document_id,
        )

        try:
            vector_store.delete_version(version_id)
        except Exception:
            logger.exception(
                "Failed to clean partially indexed version %s.",
                version_id,
            )

        _remove_file(stored_path)
        raise

    try:
        old_record = sqlite_store.save_document_version(
            record,
            prepared["chunks"],
        )
    except Exception:
        # The new version was indexed but not activated in SQLite.
        # Delete those vectors so the failed version stays inactive.
        logger.exception(
            "Could not persist document metadata for %s.",
            document_id,
        )

        try:
            vector_store.delete_version(version_id)
        except Exception:
            logger.exception(
                "Could not clean vectors for failed version %s.",
                version_id,
            )

        _remove_file(stored_path)
        raise

    # The SQLite transaction has now made the new version active.
    # Old vector records are excluded by the active-version filter
    # even if physical cleanup fails.
    if old_record:
        old_version = old_record["active_version_id"]

        try:
            vector_store.delete_version(old_version)
        except Exception:
            logger.exception(
                "Old vectors for %s need cleanup.",
                old_version,
            )

        try:
            _remove_file(old_record["stored_path"])
        except OSError:
            logger.exception(
                "Could not remove the old PDF file for %s.",
                document_id,
            )

    updated_record = sqlite_store.get_document(document_id)

    logger.info(
        "Document %s is active with %s chunks.",
        document_id,
        record["chunk_count"],
    )

    return _public_document(updated_record)


def add_document(filename: str, pdf_bytes: bytes) -> dict:
    safe_name = _safe_filename(filename)

    document_id = str(uuid.uuid4())

    return _store_version(
        document_id=document_id,
        filename=safe_name,
        pdf_bytes=pdf_bytes,
        previous_record=None,
    )


def replace_document(
    document_id: str,
    filename: str,
    pdf_bytes: bytes,
) -> dict:
    existing = sqlite_store.get_document(document_id)

    if existing is None:
        raise KeyError(
            f"Document '{document_id}' was not found."
        )

    if existing["status"] != "ready":
        raise RuntimeError(
            "This document is not available for replacement."
        )

    safe_name = _safe_filename(filename)

    return _store_version(
        document_id=document_id,
        filename=safe_name,
        pdf_bytes=pdf_bytes,
        previous_record=existing,
    )


def delete_document(document_id: str) -> dict:
    record = sqlite_store.mark_document_deleting(
        document_id
    )

    # The document is no longer eligible for semantic retrieval.
    # If deletion fails, its status remains "deleting", so it cannot
    # reappear in search results.
    try:
        vector_store.delete_version(
            record["active_version_id"]
        )
    except Exception as exc:
        logger.exception(
            "Vector cleanup failed for document %s.",
            document_id,
        )

        raise RuntimeError(
            "The document was marked for deletion, but its vector "
            "records could not yet be removed. Retry deletion."
        ) from exc

    try:
        _remove_file(record["stored_path"])
    except OSError as exc:
        logger.exception(
            "Could not remove the PDF file for %s.",
            document_id,
        )

        raise RuntimeError(
            "The document is no longer searchable, but its stored "
            "PDF could not be removed. Retry deletion."
        ) from exc

    sqlite_store.delete_document_record(document_id)

    logger.info(
        "Deleted document %s.",
        document_id,
    )

    return _public_document(record)