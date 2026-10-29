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

    # Local LLM settings
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
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

    semantic_top_k: int = 3
    min_semantic_score: float = 0.60

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

        if self.semantic_top_k <= 0:
            raise ValueError(
                "SEMANTIC_TOP_K must be greater than zero."
            )

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