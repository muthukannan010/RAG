from functools import lru_cache
from threading import Lock

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import settings


_model_lock = Lock()


@lru_cache(maxsize=1)
def _load_model(model_name: str, device: str):
    """
    Load the embedding model once per model/device combination.
    """

    with _model_lock:
        return SentenceTransformer(
            model_name,
            device=device,
        )


def _encode(texts, mode: str):
    if not texts:
        return np.empty((0, 0), dtype=np.float32)

    model = _load_model(
        settings.embedding_model,
        settings.embedding_device,
    )

    # Use task-aware methods when supported by the installed
    # Sentence Transformers model/API.
    if mode == "query" and hasattr(model, "encode_query"):
        vectors = model.encode_query(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    elif (
        mode == "document"
        and hasattr(model, "encode_document")
    ):
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

    return _encode([query], mode="query")[0]