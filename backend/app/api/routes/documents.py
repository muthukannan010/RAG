import logging
from pathlib import Path
import uuid

from fastapi import (
    APIRouter,
    Body,
    File,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse, Response

from app.core.config import settings
from app.db import sqlite_store
from app.models.schema import (
    DocumentListResponse,
    PDFPagePreviewRequest,
)
from app.services import document_service
from app.services.citations import quote_matches_source
from app.services.pdf_preview import render_pdf_page


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/documents",
    tags=["Documents"],
)


def _read_pdf_upload(file: UploadFile) -> bytes:
    filename = file.filename or ""

    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=422,
            detail="Only PDF documents are supported.",
        )

    # Read at most the permitted size plus one byte.
    # This avoids loading an arbitrarily large request into memory.
    maximum_bytes = settings.max_upload_mb * 1024 * 1024

    try:
        content = file.file.read(maximum_bytes + 1)
    finally:
        file.file.close()

    if len(content) > maximum_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"The maximum upload size is "
                f"{settings.max_upload_mb} MB."
            ),
        )

    return content


@router.get(
    "",
    response_model=DocumentListResponse,
)
def list_documents():
    return {
        "documents": document_service.list_documents()
    }


@router.post(
    "/upload",
    status_code=201,
)
def upload_document(
    file: UploadFile = File(...),
):
    content = _read_pdf_upload(file)

    try:
        document = document_service.add_document(
            file.filename or "",
            content,
        )

        return {
            "message": (
                "PDF uploaded and indexed for semantic search."
            ),
            "document": document,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception("Document upload failed.")

        raise HTTPException(
            status_code=500,
            detail="The server could not process the uploaded PDF.",
        ) from exc


@router.put("/{document_id}")
def replace_document(
    document_id: str,
    file: UploadFile = File(...),
):
    content = _read_pdf_upload(file)

    try:
        document = document_service.replace_document(
            document_id=document_id,
            filename=file.filename or "",
            pdf_bytes=content,
        )

        return {
            "message": (
                "The document was replaced and re-indexed."
            ),
            "document": document,
        }

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "Document replacement failed for %s.",
            document_id,
        )

        raise HTTPException(
            status_code=500,
            detail="The server could not replace the document.",
        ) from exc


@router.delete("/{document_id}")
def delete_document(document_id: str):
    try:
        document_service.delete_document(
            document_id
        )

        return {
            "message": (
                f"Document '{document_id}' was deleted."
            )
        }

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "Document deletion failed for %s.",
            document_id,
        )

        raise HTTPException(
            status_code=500,
            detail="The server could not delete the document.",
        ) from exc


@router.get("/{document_id}/file")
def get_document_file(document_id: str):
    """
    Serve the original PDF through the API so the frontend
    can open its cited page.
    """

    record = sqlite_store.get_document(document_id)

    if record is None or record["status"] != "ready":
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    path = Path(record["stored_path"]).resolve()
    allowed_root = settings.documents_dir.resolve()

    # Only serve files inside the configured document directory.
    if not path.is_relative_to(allowed_root):
        logger.error(
            "Invalid stored path detected for document %s.",
            document_id,
        )

        raise HTTPException(
            status_code=500,
            detail="The stored document path is invalid.",
        )

    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="The PDF file is no longer available.",
        )

    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "no-store",
        },
    )


@router.post("/{document_id}/pages/{page_number}/preview")
def get_document_page_preview(
    document_id: str,
    page_number: int,
    request: PDFPagePreviewRequest = Body(...),
):
    """Render one PDF page and highlight a verified citation quote."""

    try:
        uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="The document ID is invalid.",
        ) from exc

    record = sqlite_store.get_document(document_id)
    if record is None or record["status"] != "ready":
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    if page_number < 1 or page_number > record["page_count"]:
        raise HTTPException(
            status_code=404,
            detail="The requested PDF page does not exist.",
        )

    quote = request.quoted_text
    if quote:
        active_chunks = sqlite_store.get_active_chunks_for_page(
            document_id,
            page_number,
        )
        quote_is_verified = any(
            quote_matches_source(quote, chunk["content"])
            for chunk in active_chunks
        )
        if not quote_is_verified:
            quote = None

    path = Path(record["stored_path"]).resolve()
    allowed_root = settings.documents_dir.resolve()
    if not path.is_relative_to(allowed_root):
        logger.error(
            "Invalid stored path detected for document %s.",
            document_id,
        )
        raise HTTPException(
            status_code=500,
            detail="The stored document path is invalid.",
        )

    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="The PDF file is no longer available.",
        )

    try:
        image, highlight_matched, highlight_y = render_pdf_page(
            path,
            page_number,
            quote,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception(
            "Could not render page %s of document %s.",
            page_number,
            document_id,
        )
        raise HTTPException(
            status_code=500,
            detail="The PDF page could not be rendered.",
        ) from exc

    return Response(
        content=image,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-PDF-Page-Count": str(record["page_count"]),
            "X-PDF-Highlight-Matched": str(highlight_matched).lower(),
            "X-PDF-Highlight-Y": (
                "" if highlight_y is None else str(highlight_y)
            ),
        },
    )