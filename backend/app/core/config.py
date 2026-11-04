import math
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    reset_data_on_startup: bool = False
    # Local LLM settings
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "mistral-nemo:12b"
    ollama_timeout_seconds: int = 120

    # RAG context preparation
    rag_max_context_chunks: int = 5
    rag_max_context_chars: int = 12000

    # Generation options
    llm_max_output_tokens: int = 512
    llm_temperature: float = 0.1

    app_name: str = "Local RAG Assistant"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    data_dir: Path = BACKEND_ROOT / "data"
    documents_dir: Path = BACKEND_ROOT / "data" / "documents"
    sqlite_db_path: Path = BACKEND_ROOT / "data" / "rag.sqlite3"
    chroma_db_path: Path = BACKEND_ROOT / "data" / "chroma"

    embedding_model: str = (
        "sentence-transformers/all-MiniLM-L6-v2"
    )
    embedding_device: str = "cpu"

    chunk_size_chars: int = 600
    chunk_overlap_chars: int = 150

    keyword_top_k: int = 20
    semantic_top_k: int = 20
    hybrid_top_k: int = 5
    keyword_weight: float = 0.40
    semantic_weight: float = 0.60
    rrf_k: int = 60
    enable_keyword_search: bool = True
    enable_semantic_search: bool = True
    remove_duplicate_chunks: bool = True
    min_semantic_score: float = 0.40

    max_upload_mb: int = 100

    chroma_collection_name: str = "pdf_chunks"

    @model_validator(mode="after")
    def validate_settings(self):
        if self.chunk_size_chars <= 0:
            raise ValueError(
                "CHUNK_SIZE_CHARS must be greater than zero."
            )

        if not (
            0 <= self.chunk_overlap_chars < self.chunk_size_chars
        ):
            raise ValueError(
                "CHUNK_OVERLAP_CHARS must be non-negative "
                "and smaller than CHUNK_SIZE_CHARS."
            )

        if (
            self.keyword_top_k <= 0
            or self.semantic_top_k <= 0
            or self.hybrid_top_k <= 0
        ):
            raise ValueError(
                "Retrieval top-K settings must be greater than zero."
            )

        if self.rrf_k <= 0:
            raise ValueError("RRF_K must be greater than zero.")

        if (
            not math.isfinite(self.keyword_weight)
            or not math.isfinite(self.semantic_weight)
            or self.keyword_weight < 0
            or self.semantic_weight < 0
        ):
            raise ValueError("Retrieval weights must be non-negative.")

        if not (
            self.enable_keyword_search
            or self.enable_semantic_search
        ):
            raise ValueError(
                "At least one retrieval method must be enabled."
            )

        if self.enable_keyword_search and self.enable_semantic_search:
            total_weight = self.keyword_weight + self.semantic_weight
            if total_weight <= 0:
                raise ValueError(
                    "At least one retrieval weight must be positive."
                )
            self.keyword_weight /= total_weight
            self.semantic_weight /= total_weight
        elif self.enable_keyword_search:
            self.keyword_weight = 1.0
            self.semantic_weight = 0.0
        else:
            self.keyword_weight = 0.0
            self.semantic_weight = 1.0

        if self.max_upload_mb <= 0:
            raise ValueError(
                "MAX_UPLOAD_MB must be greater than zero."
            )

        if not -1.0 <= self.min_semantic_score <= 1.0:
            raise ValueError(
                "MIN_SEMANTIC_SCORE must be between -1 and 1."
            )
        if self.ollama_timeout_seconds <= 0:
            raise ValueError(
                "OLLAMA_TIMEOUT_SECONDS must be positive."
            )

        if self.rag_max_context_chunks <= 0:
            raise ValueError(
                "RAG_MAX_CONTEXT_CHUNKS must be positive."
            )

        if self.rag_max_context_chars <= 0:
            raise ValueError(
                "RAG_MAX_CONTEXT_CHARS must be positive."
            )

        if self.llm_max_output_tokens <= 0:
            raise ValueError(
                "LLM_MAX_OUTPUT_TOKENS must be positive."
            )

        if not 0 <= self.llm_temperature <= 2:
            raise ValueError(
                "LLM_TEMPERATURE must be between 0 and 2."
            )

        return self


settings = Settings()