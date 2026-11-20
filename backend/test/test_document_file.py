import re
import uuid
from urllib.parse import unquote

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.api.routes import documents
from app.main import app


@pytest.mark.parametrize(
    ("extension", "expected_media_type"),
    [
        (".pdf", "application/pdf"),
        (
            ".docx",
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document",
        ),
        (
            ".pptx",
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation",
        ),
        (
            ".xlsx",
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet",
        ),
        (".txt", "text/plain"),
        (".csv", "text/csv"),
        (".md", "text/markdown"),
        (".html", "text/html"),
        (".json", "application/json"),
        (".xml", "application/xml"),
    ],
)
def test_file_endpoint_returns_original_bytes_and_media_type(
    tmp_path,
    monkeypatch,
    extension,
    expected_media_type,
):
    document_id = str(uuid.uuid4())
    filename = f"original{extension}"
    stored_path = tmp_path / document_id / f"version{extension}"
    original_bytes = b"\x00original document bytes\xff"
    record = {
        "status": "ready",
        "filename": filename,
        "stored_path": str(stored_path),
    }

    monkeypatch.setattr(
        documents.settings,
        "documents_dir",
        tmp_path,
    )
    monkeypatch.setattr(
        documents.sqlite_store,
        "get_document",
        lambda value: record if value == document_id else None,
    )

    with TestClient(app) as client:
        stored_path.parent.mkdir(parents=True, exist_ok=True)
        stored_path.write_bytes(original_bytes)
        response = client.get(
            f"/api/v1/documents/{document_id}/file"
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        expected_media_type
    )
    assert response.content == original_bytes
    assert response.headers["cache-control"] == "no-store"


def test_file_endpoint_encodes_original_filename_safely(
    tmp_path,
    monkeypatch,
):
    document_id = str(uuid.uuid4())
    filename = "Résumé report; (draft) #1\r\nX-Evil: injected.docx"
    stored_path = tmp_path / document_id / "version.docx"
    record = {
        "status": "ready",
        "filename": filename,
        "stored_path": str(stored_path),
    }

    monkeypatch.setattr(
        documents.settings,
        "documents_dir",
        tmp_path,
    )
    monkeypatch.setattr(
        documents.sqlite_store,
        "get_document",
        lambda value: record if value == document_id else None,
    )

    with TestClient(app) as client:
        stored_path.parent.mkdir(parents=True, exist_ok=True)
        stored_path.write_bytes(b"docx bytes")
        response = client.get(
            f"/api/v1/documents/{document_id}/file"
        )

    disposition = response.headers["content-disposition"]
    encoded_filename = re.search(
        r"filename\*=utf-8''([^;]+)",
        disposition,
        flags=re.IGNORECASE,
    )

    assert response.status_code == 200
    assert disposition.startswith("inline;")
    assert encoded_filename is not None
    assert unquote(encoded_filename.group(1)) == filename
    assert "\r" not in disposition
    assert "\n" not in disposition


@pytest.mark.parametrize(
    ("record", "expected_status", "expected_detail"),
    [
        (None, 404, "Document not found."),
        (
            {"status": "deleting"},
            404,
            "Document not found.",
        ),
    ],
)
def test_file_endpoint_requires_ready_document(
    monkeypatch,
    record,
    expected_status,
    expected_detail,
):
    monkeypatch.setattr(
        documents.sqlite_store,
        "get_document",
        lambda _document_id: record,
    )

    with pytest.raises(HTTPException) as error:
        documents.get_document_file("document-id")

    assert error.value.status_code == expected_status
    assert error.value.detail == expected_detail


def test_file_endpoint_rejects_paths_outside_document_directory(
    tmp_path,
    monkeypatch,
):
    outside_path = tmp_path / "outside.pdf"
    outside_path.write_bytes(b"not served")
    monkeypatch.setattr(
        documents.settings,
        "documents_dir",
        tmp_path / "documents",
    )
    monkeypatch.setattr(
        documents.sqlite_store,
        "get_document",
        lambda _document_id: {
            "status": "ready",
            "filename": "outside.pdf",
            "stored_path": str(outside_path),
        },
    )

    with pytest.raises(HTTPException) as error:
        documents.get_document_file("document-id")

    assert error.value.status_code == 500
    assert error.value.detail == "The stored document path is invalid."


def test_file_endpoint_returns_not_found_for_missing_stored_file(
    tmp_path,
    monkeypatch,
):
    missing_path = tmp_path / "documents" / "version.docx"
    monkeypatch.setattr(
        documents.settings,
        "documents_dir",
        tmp_path,
    )
    monkeypatch.setattr(
        documents.sqlite_store,
        "get_document",
        lambda _document_id: {
            "status": "ready",
            "filename": "sample.docx",
            "stored_path": str(missing_path),
        },
    )

    with pytest.raises(HTTPException) as error:
        documents.get_document_file("document-id")

    assert error.value.status_code == 404
    assert error.value.detail == (
        "The original document file is no longer available."
    )
