import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.services import hybrid_retrieval


def _result(chunk_id: str, content: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "document_id": "document-1",
        "version_id": "version-1",
        "filename": "sample.pdf",
        "page_number": 1,
        "content": content,
        "bbox": [],
    }


@pytest.fixture
def hybrid_settings(monkeypatch):
    values = {
        "enable_keyword_search": True,
        "enable_semantic_search": True,
        "keyword_top_k": 20,
        "semantic_top_k": 20,
        "hybrid_top_k": 5,
        "keyword_weight": 0.4,
        "semantic_weight": 0.6,
        "rrf_k": 60,
        "remove_duplicate_chunks": False,
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)


def test_hybrid_search_merges_duplicates_and_ranks_with_weighted_rrf(
    monkeypatch,
    hybrid_settings,
):
    keyword_results = [
        {**_result("shared", "shared passage"), "keyword_score": -2.0},
        {**_result("keyword-only", "exact phrase"), "keyword_score": -1.0},
    ]
    semantic_results = [
        {**_result("semantic-only", "meaning match"), "semantic_score": 0.8},
        {**_result("shared", "shared passage"), "semantic_score": 0.7},
    ]
    monkeypatch.setattr(
        hybrid_retrieval,
        "keyword_search",
        lambda query, top_k: keyword_results,
    )
    monkeypatch.setattr(
        hybrid_retrieval,
        "semantic_search",
        lambda query, top_k: semantic_results,
    )

    results = hybrid_retrieval.hybrid_search(
        "test query",
        top_k=2,
    )

    assert [item["chunk_id"] for item in results] == [
        "shared",
        "semantic-only",
    ]
    assert results[0]["keyword_rank"] == 1
    assert results[0]["semantic_rank"] == 2
    assert results[0]["keyword_score"] == -2.0
    assert results[0]["semantic_score"] == 0.7
    assert results[0]["hybrid_score"] == pytest.approx(
        0.4 / 61 + 0.6 / 62
    )


def test_hybrid_search_supports_keyword_only_and_semantic_only(
    monkeypatch,
    hybrid_settings,
):
    keyword_candidate = {
        **_result("keyword-only", "exact term"),
        "keyword_score": -1.0,
    }
    semantic_candidate = {
        **_result("semantic-only", "meaning match"),
        "semantic_score": 0.8,
    }
    monkeypatch.setattr(
        hybrid_retrieval,
        "keyword_search",
        lambda query, top_k: [keyword_candidate],
    )
    monkeypatch.setattr(
        hybrid_retrieval,
        "semantic_search",
        lambda query, top_k: [semantic_candidate],
    )

    monkeypatch.setattr(settings, "enable_semantic_search", False)
    monkeypatch.setattr(settings, "keyword_weight", 1.0)
    keyword_results = hybrid_retrieval.hybrid_search("exact term")
    assert [item["chunk_id"] for item in keyword_results] == [
        "keyword-only"
    ]
    assert keyword_results[0]["hybrid_score"] == pytest.approx(
        1 / 61
    )

    monkeypatch.setattr(settings, "enable_semantic_search", True)
    monkeypatch.setattr(settings, "enable_keyword_search", False)
    monkeypatch.setattr(settings, "keyword_weight", 0.0)
    monkeypatch.setattr(settings, "semantic_weight", 1.0)
    semantic_results = hybrid_retrieval.hybrid_search("meaning")
    assert [item["chunk_id"] for item in semantic_results] == [
        "semantic-only"
    ]
    assert semantic_results[0]["hybrid_score"] == pytest.approx(
        1 / 61
    )


def test_hybrid_search_removes_duplicate_text_when_enabled(
    monkeypatch,
    hybrid_settings,
):
    duplicate_candidates = [
        {
            **_result("chunk-1", "Same   passage."),
            "keyword_score": -1.0,
        },
        {
            **_result("chunk-2", "Same passage."),
            "keyword_score": -2.0,
        },
    ]
    monkeypatch.setattr(
        hybrid_retrieval,
        "keyword_search",
        lambda query, top_k: duplicate_candidates,
    )
    monkeypatch.setattr(
        hybrid_retrieval,
        "semantic_search",
        lambda query, top_k: [],
    )
    monkeypatch.setattr(settings, "enable_semantic_search", False)
    monkeypatch.setattr(settings, "keyword_weight", 1.0)
    monkeypatch.setattr(settings, "remove_duplicate_chunks", True)

    results = hybrid_retrieval.hybrid_search("same passage")

    assert [item["chunk_id"] for item in results] == ["chunk-1"]


def test_settings_normalize_weights_and_reject_invalid_retrieval_config():
    normalized = Settings(
        keyword_weight=2,
        semantic_weight=3,
    )
    assert normalized.keyword_weight == pytest.approx(0.4)
    assert normalized.semantic_weight == pytest.approx(0.6)

    with pytest.raises(ValidationError):
        Settings(
            enable_keyword_search=False,
            enable_semantic_search=False,
        )

    with pytest.raises(ValidationError):
        Settings(
            keyword_weight=-0.1,
            semantic_weight=1.1,
        )
