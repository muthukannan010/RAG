import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import documents, search
from app.core.config import settings
from app.core.logging_config import configure_logging
from app.db import sqlite_store, vector_store


configure_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize persistent storage when FastAPI starts.
    """

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.documents_dir.mkdir(parents=True, exist_ok=True)
    settings.chroma_db_path.mkdir(parents=True, exist_ok=True)

    sqlite_store.initialize_database()
    vector_store.get_collection()

    # Remove inactive/orphaned vectors left by interrupted
    # uploads, replacements or deletions.
    vector_store.cleanup_inactive_versions()

    logger.info(
        "Application startup complete. Storage: %s",
        settings.data_dir,
    )

    yield

    logger.info("Application shutdown complete.")


app = FastAPI(
    title=settings.app_name,
    description=(
        "On-premises PDF ingestion and semantic search API."
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
    return {
        "status": "ok",
        "application": settings.app_name,
        "retrieval_mode": "semantic",
    }