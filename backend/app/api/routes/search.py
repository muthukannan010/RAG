import logging

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.models.schema import SearchRequest, SearchResponse
from app.services.retrieval import semantic_search


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/search",
    tags=["Search"],
)


@router.post(
    "",
    response_model=SearchResponse,
)
def search_documents(request: SearchRequest):
    top_k = (
        request.top_k
        if request.top_k is not None
        else settings.semantic_top_k
    )

    try:
        results = semantic_search(
            query=request.query,
            top_k=top_k,
        )

        return {
            "query": request.query,
            "answer": None,
            "retrieval_mode": "semantic",
            "results": results,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception("Semantic search failed.")

        raise HTTPException(
            status_code=500,
            detail="The server could not search the documents.",
        ) from exc