import logging

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.models.schema import SearchRequest, SearchResponse
from app.services.llm import LLMServiceError
from app.services.rag import answer_question


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
    """
    Retrieve semantically relevant PDF passages and generate
    a grounded answer using the local LLM.
    """

    top_k = (
        request.top_k
        if request.top_k is not None
        else settings.semantic_top_k
    )

    try:
        return answer_question(
            query=request.query,
            top_k=top_k,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except LLMServiceError as exc:
        logger.warning(
            "Local answer generation failed: %s",
            exc,
        )

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "RAG answer generation failed."
        )

        raise HTTPException(
            status_code=500,
            detail="The server could not answer the question.",
        ) from exc