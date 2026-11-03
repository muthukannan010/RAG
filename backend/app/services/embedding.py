
import logging
from threading import Lock

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import settings


logger = logging.getLogger(__name__)

_model = None
_model_key = None
_model_lock = Lock()


def get_embedding_model():
    """Load the embedding model once and reuse it."""

    global _model, _model_key

    model_key = (
        settings.embedding_model,
        settings.embedding_device,
    )

    if _model is None or _model_key != model_key:
        with _model_lock:
            if _model is None or _model_key != model_key:
                logger.info(
                    "Loading local embedding model: %s",
                    settings.embedding_model,
                )

                _model = SentenceTransformer(
                    settings.embedding_model,
                    device=settings.embedding_device,
                    local_files_only=True,
                )

                _model_key = model_key

                logger.info("Embedding model loaded successfully.")

    return _model


def _encode(texts: list[str], mode: str) -> np.ndarray:
    """Generate normalized embeddings for documents or queries."""

    if not texts:
        return np.empty((0, 0), dtype=np.float32)

    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ValueError("Embedding inputs must contain non-empty text.")

    model = get_embedding_model()

    if mode == "query" and hasattr(model, "encode_query"):
        vectors = model.encode_query(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    elif mode == "document" and hasattr(model, "encode_document"):
        vectors = model.encode_document(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    else:
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    return np.asarray(vectors, dtype=np.float32)


def embed_texts(texts: list[str]) -> np.ndarray:
    """Generate embeddings for PDF chunks."""

    return _encode(texts, mode="document")


def embed_query(query: str) -> np.ndarray:
    """Generate an embedding for a user's question."""

    if not query or not query.strip():
        raise ValueError("The search query cannot be empty.")

    return _encode([query], mode="query")[0]
