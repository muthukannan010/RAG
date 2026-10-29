import json
import logging

import chromadb

from app.core.config import settings


logger = logging.getLogger(__name__)

_client = None
_collection = None
_collection_path = None


def get_collection():
    global _client, _collection, _collection_path

    current_path = str(settings.chroma_db_path.resolve())

    if _collection is None or _collection_path != current_path:
        settings.chroma_db_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        _client = chromadb.PersistentClient(
            path=current_path
        )

        _collection = _client.get_or_create_collection(
            name=settings.chroma_collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        _collection_path = current_path

        logger.info(
            "Opened persistent Chroma collection '%s'.",
            settings.chroma_collection_name,
        )

    return _collection


def upsert_chunks(
    document_id,
    version_id,
    filename,
    chunks,
    embeddings,
) -> None:
    if not chunks:
        return

    if len(chunks) != len(embeddings):
        raise ValueError(
            "Every chunk must have exactly one embedding."
        )

    collection = get_collection()

    collection.upsert(
        ids=[chunk["id"] for chunk in chunks],
        embeddings=embeddings.tolist(),
        documents=[chunk["text"] for chunk in chunks],
        metadatas=[
            {
                "document_id": document_id,
                "version_id": version_id,
                "filename": filename,
                "page_number": int(chunk["page_number"]),
                "chunk_index": int(chunk["chunk_index"]),
                "bbox_json": json.dumps(chunk["bbox"]),
            }
            for chunk in chunks
        ],
    )

    logger.info(
        "Indexed %s chunks for document %s.",
        len(chunks),
        document_id,
    )


def delete_version(version_id: str) -> None:
    collection = get_collection()

    collection.delete(
        where={"version_id": version_id}
    )

    logger.info(
        "Removed vector records for version %s.",
        version_id,
    )


def query_chunks(
    query_embedding,
    active_version_ids,
    top_k: int,
):
    if not active_version_ids:
        return []

    collection = get_collection()
    count = collection.count()

    if count == 0:
        return []

    result_count = min(top_k, count)

    results = collection.query(
        query_embeddings=[query_embedding.tolist()],
        n_results=result_count,
        where={
            "version_id": {
                "$in": active_version_ids
            }
        },
        include=[
            "documents",
            "metadatas",
            "distances",
        ],
    )

    ids = results.get("ids", [[]])[0]
    texts = results.get("documents", [[]])[0]
    metadata_items = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    output = []

    for chunk_id, text, metadata, distance in zip(
        ids,
        texts,
        metadata_items,
        distances,
    ):
        # Chroma's cosine distance is based on 1 - similarity.
        similarity = max(
            -1.0,
            min(1.0, 1.0 - float(distance)),
        )

        try:
            bounding_boxes = json.loads(
                metadata.get("bbox_json", "[]")
            )
        except (TypeError, ValueError):
            bounding_boxes = []

        output.append(
            {
                "chunk_id": chunk_id,
                "document_id": metadata["document_id"],
                "version_id": metadata["version_id"],
                "filename": metadata["filename"],
                "page_number": int(metadata["page_number"]),
                "content": text,
                "semantic_score": similarity,
                "bbox": bounding_boxes,
            }
        )

    return output


def cleanup_inactive_versions() -> None:
    """
    Remove orphaned or obsolete vector records.

    This is also run during startup to recover from interruptions
    during previous indexing, replacement or deletion operations.
    """

    from app.db import sqlite_store

    collection = get_collection()

    if collection.count() == 0:
        return

    active_versions = set(
        sqlite_store.get_active_version_ids()
    )

    stored = collection.get(
        include=["metadatas"]
    )

    inactive_versions = {
        metadata["version_id"]
        for metadata in stored.get("metadatas", [])
        if metadata
        and metadata.get("version_id") not in active_versions
    }

    for version_id in inactive_versions:
        delete_version(version_id)

    if inactive_versions:
        logger.info(
            "Cleaned %s inactive vector versions.",
            len(inactive_versions),
        )