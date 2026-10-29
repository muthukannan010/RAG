import hashlib
import re

import numpy as np
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import ingestion, retrieval


def fake_embedding(text: str) -> np.ndarray:
    """
    Deterministic test double.

    It allows tests to exercise the indexing pipeline without
    downloading or loading the real embedding model.
    It is not a substitute for evaluating real semantic quality.
    """

    vector = np.zeros(256, dtype=np.float32)

    for token in re.findall(r"[a-z0-9]+", text.lower()):
        digest = hashlib.sha256(
            token.encode("utf-8")
        ).digest()

        index = int.from_bytes(
            digest[:4],
            byteorder="big",
        ) % len(vector)

        vector[index] += 1.0

    norm = np.linalg.norm(vector)

    if norm > 0:
        vector /= norm

    return vector


def make_test_pdf(text: str) -> bytes:
    """Create a small PDF in memory for automated tests."""

    document = pymupdf.open()

    try:
        page = document.new_page()
        page.insert_text(
            (72, 72),
            text,
            fontsize=12,
        )

        return document.tobytes()

    finally:
        document.close()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_semantic_upload_replace_delete_flow(
    client,
    monkeypatch,
):
    # Replace real model calls with deterministic test embeddings.
    monkeypatch.setattr(
        ingestion,
        "embed_texts",
        lambda texts: np.vstack(
            [fake_embedding(text) for text in texts]
        ),
    )

    monkeypatch.setattr(
        retrieval,
        "embed_query",
        fake_embedding,
    )

    # 1. Upload the initial PDF.
    original_pdf = make_test_pdf(
        "The secret moonstone code is alpha731. "
        "This document describes the original procedure."
    )

    upload_response = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "original.pdf",
                original_pdf,
                "application/pdf",
            )
        },
    )

    assert upload_response.status_code == 201

    uploaded = upload_response.json()["document"]
    document_id = uploaded["id"]

    assert uploaded["status"] == "ready"
    assert uploaded["chunk_count"] > 0

    # 2. Check that the document appears in the library.
    list_response = client.get(
        "/api/v1/documents"
    )

    assert list_response.status_code == 200

    listed_ids = {
        item["id"]
        for item in list_response.json()["documents"]
    }

    assert document_id in listed_ids

    # 3. Search the uploaded document semantically.
    search_response = client.post(
        "/api/v1/search",
        json={
            "query": (
                "Tell me the secret moonstone code alpha731"
            )
        },
    )

    assert search_response.status_code == 200

    search_payload = search_response.json()
    initial_results = search_payload["results"]

    assert initial_results
    assert any(
        item["document_id"] == document_id
        for item in initial_results
    )

    assert all(
        item["semantic_score"] >= 0
        for item in initial_results
    )

    assert any(
        "moonstone" in item["content"].lower()
        for item in initial_results
    )

    # 4. Replace the existing PDF with different content.
    replacement_pdf = make_test_pdf(
        "The glacier procedure stores blue ice samples. "
        "This document describes a different procedure."
    )

    replace_response = client.put(
        f"/api/v1/documents/{document_id}",
        files={
            "file": (
                "replacement.pdf",
                replacement_pdf,
                "application/pdf",
            )
        },
    )

    assert replace_response.status_code == 200

    replaced = replace_response.json()["document"]

    assert replaced["id"] == document_id
    assert replaced["filename"] == "replacement.pdf"

    # 5. Ensure the obsolete text is not retrievable.
    stale_search = client.post(
        "/api/v1/search",
        json={
            "query": (
                "Tell me the secret moonstone code alpha731"
            )
        },
    )

    assert stale_search.status_code == 200

    assert not any(
        "moonstone" in item["content"].lower()
        for item in stale_search.json()["results"]
    )

    # 6. Confirm the replacement content is searchable.
    replacement_search = client.post(
        "/api/v1/search",
        json={
            "query": "glacier blue ice samples procedure"
        },
    )

    assert replacement_search.status_code == 200

    assert any(
        "glacier" in item["content"].lower()
        for item in replacement_search.json()["results"]
    )

    # 7. Delete the document.
    delete_response = client.delete(
        f"/api/v1/documents/{document_id}"
    )

    assert delete_response.status_code == 200

    # 8. The deleted document must not appear in the list.
    final_list = client.get(
        "/api/v1/documents"
    ).json()["documents"]

    assert all(
        item["id"] != document_id
        for item in final_list
    )

    # 9. No vectors from the deleted document may be retrieved.
    final_search = client.post(
        "/api/v1/search",
        json={
            "query": "glacier blue ice samples procedure"
        },
    )

    assert final_search.status_code == 200
    assert final_search.json()["results"] == []


def test_chunker_preserves_page_and_bounding_boxes():
    from app.services.chunker import chunk_pages

    text = (
        "The semantic retrieval process identifies related passages. "
        "Chunk boundaries preserve meaningful context. "
    ) * 15

    pages = [
        {
            "page_number": 3,
            "blocks": [
                {
                    "text": text,
                    "bbox": [72.0, 100.0, 450.0, 600.0],
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

    assert all(
        chunk["page_number"] == 3
        for chunk in chunks
    )

    assert all(
        chunk["bbox"]
        for chunk in chunks
    )

    assert all(
        chunk["text"]
        for chunk in chunks
    )

    assert len({
        chunk["id"]
        for chunk in chunks
    }) == len(chunks)