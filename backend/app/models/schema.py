from pydantic import BaseModel, Field, field_validator


class DocumentSummary(BaseModel):
    id: str
    filename: str
    size_bytes: int
    page_count: int
    chunk_count: int
    status: str
    created_at: str
    updated_at: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]


class DocumentMutationResponse(BaseModel):
    message: str
    document: DocumentSummary | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("The query cannot be empty.")

        return value


class SearchResult(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    page_number: int
    content: str
    semantic_score: float
    relevance_score: float
    bbox: list[list[float]]


class SearchResponse(BaseModel):
    query: str
    answer: str | None = None
    retrieval_mode: str = "semantic"
    results: list[SearchResult]