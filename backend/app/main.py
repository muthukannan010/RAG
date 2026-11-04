import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
import shutil
from pathlib import Path
from app.api.routes import documents, search
from app.core.config import settings
from app.core.logging_config import configure_logging
from app.db import sqlite_store, vector_store


configure_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):

    # Start every new application run with an empty workspace.
    if settings.reset_data_on_startup:
        reset_application_data()

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.documents_dir.mkdir(parents=True, exist_ok=True)
    settings.chroma_db_path.mkdir(parents=True, exist_ok=True)

    sqlite_store.initialize_database()
    vector_store.get_collection()

    logger.info("Application startup complete.")

    yield

    logger.info("Application shutdown complete.")
app = FastAPI(
    title=settings.app_name,
    description=(
        "On-premises PDF ingestion and hybrid retrieval API."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


app.include_router(
    documents.router,
    prefix=settings.api_prefix,
)

app.include_router(
    search.router,
    prefix=settings.api_prefix,
)


@app.get(
    f"{settings.api_prefix}/health",
    tags=["Health"],
)
def health_check():
    if settings.enable_keyword_search and settings.enable_semantic_search:
        retrieval_mode = "hybrid"
    elif settings.enable_keyword_search:
        retrieval_mode = "keyword"
    else:
        retrieval_mode = "semantic"

    return {
        "status": "ok",
        "application": settings.app_name,
        "retrieval_mode": retrieval_mode,
    }
def reset_application_data():
    """Clear previously uploaded documents and their indexes."""

    # Remove uploaded PDFs
    shutil.rmtree(
        settings.documents_dir,
        ignore_errors=True,
    )

    # Remove ChromaDB vectors
    shutil.rmtree(
        settings.chroma_db_path,
        ignore_errors=True,
    )

    # Remove SQLite database and temporary journal files
    for suffix in ("", "-wal", "-shm"):
        db_file = Path(f"{settings.sqlite_db_path}{suffix}")
        db_file.unlink(missing_ok=True)

    logger.info("Previous application data cleared.")