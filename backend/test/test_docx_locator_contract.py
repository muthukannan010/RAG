import pytest
from pydantic import ValidationError

from app.models.schema import (
    DOCXChunkLocator,
    DOCXLocatorSegment,
    SearchResult,
)


def _paragraph_locator(**overrides):
    locator = {
        "document_version_id": "version-1",
        "part_name": "word/document.xml",
        "element_type": "paragraph",
        "structural_path": [{"kind": "paragraph", "index": 3}],
        "paragraph_index": 3,
        "text_range": {"start": 0, "end": 18},
        "section_path": ["Overview"],
        "mapping_status": "resolved",
    }
    locator.update(overrides)
    return locator


def _table_cell_locator(**overrides):
    locator = {
        "document_version_id": "version-1",
        "part_name": "word/document.xml",
        "element_type": "table_cell_paragraph",
        "structural_path": [
            {"kind": "table", "index": 0},
            {"kind": "row", "index": 1},
            {"kind": "cell", "index": 2},
            {"kind": "paragraph", "index": 1},
        ],
        "paragraph_index": 12,
        "table_index": 0,
        "row_index": 1,
        "cell_index": 2,
        "cell_paragraph_index": 1,
        "text_range": {"start": 4, "end": 15},
        "section_path": ["Results"],
        "mapping_status": "resolved",
    }
    locator.update(overrides)
    return locator


def test_valid_paragraph_locator_is_verified():
    locator = DOCXLocatorSegment.model_validate(_paragraph_locator())

    assert locator.is_verified
    assert locator.structural_path[0].kind == "paragraph"
    assert locator.text_range.start == 0
    assert locator.text_range.end == 18


def test_valid_table_cell_locator_retains_physical_coordinates():
    locator = DOCXLocatorSegment.model_validate(_table_cell_locator())

    assert locator.is_verified
    assert locator.table_index == 0
    assert locator.row_index == 1
    assert locator.cell_index == 2
    assert locator.cell_paragraph_index == 1


def test_chunk_locator_supports_multiple_segments_and_overlapping_chunks():
    first_segment = DOCXLocatorSegment.model_validate(
        _paragraph_locator(
            text_range={"start": 0, "end": 12},
        )
    )
    next_paragraph = DOCXLocatorSegment.model_validate(
        _paragraph_locator(
            structural_path=[{"kind": "paragraph", "index": 4}],
            paragraph_index=4,
        )
    )
    chunk = DOCXChunkLocator(
        locator_segments=[first_segment, next_paragraph]
    )
    overlapping_chunk = DOCXChunkLocator(
        locator_segments=[
            DOCXLocatorSegment.model_validate(
                _paragraph_locator(
                    text_range={"start": 8, "end": 18},
                )
            )
        ]
    )

    assert len(chunk.locator_segments) == 2
    assert overlapping_chunk.locator_segments[0].text_range.start == 8
    assert overlapping_chunk.locator_segments[0].text_range.end == 18


def test_text_range_uses_nonempty_half_open_interval():
    locator = DOCXLocatorSegment.model_validate(
        _paragraph_locator(text_range={"start": 2, "end": 5})
    )
    assert locator.text_range.end - locator.text_range.start == 3

    with pytest.raises(ValidationError, match="end greater than start"):
        DOCXLocatorSegment.model_validate(
            _paragraph_locator(text_range={"start": 5, "end": 5})
        )

    with pytest.raises(ValidationError):
        DOCXLocatorSegment.model_validate(
            _paragraph_locator(text_range={"start": -1, "end": 5})
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"structural_path": None},
        {
            "structural_path": [
                {"kind": "row", "index": 0},
                {"kind": "cell", "index": 0},
                {"kind": "paragraph", "index": 0},
            ]
        },
        {
            "structural_path": [
                {"kind": "paragraph", "index": -1},
            ]
        },
    ],
)
def test_resolved_locator_rejects_missing_or_invalid_paths(changes):
    with pytest.raises(ValidationError):
        DOCXLocatorSegment.model_validate(_paragraph_locator(**changes))


def test_unresolved_locator_has_no_verified_path():
    locator = DOCXLocatorSegment.model_validate(
        _paragraph_locator(
            structural_path=None,
            paragraph_index=None,
            mapping_status="unresolved",
        )
    )

    assert not locator.is_verified
    assert locator.structural_path is None


def test_ambiguous_locator_keeps_candidates_unselected():
    locator = DOCXLocatorSegment.model_validate(
        _paragraph_locator(
            structural_path=None,
            paragraph_index=None,
            mapping_status="ambiguous",
            candidate_paths=[
                [{"kind": "paragraph", "index": 3}],
                [{"kind": "paragraph", "index": 8}],
            ],
        )
    )

    assert not locator.is_verified
    assert locator.structural_path is None
    assert len(locator.candidate_paths) == 2

    with pytest.raises(ValidationError, match="at least two candidates"):
        DOCXLocatorSegment.model_validate(
            _paragraph_locator(
                structural_path=None,
                paragraph_index=None,
                mapping_status="ambiguous",
                candidate_paths=[
                    [{"kind": "paragraph", "index": 3}],
                ],
            )
        )


def test_locator_requires_document_version():
    locator = _paragraph_locator()
    locator.pop("document_version_id")

    with pytest.raises(ValidationError):
        DOCXLocatorSegment.model_validate(locator)

    with pytest.raises(ValidationError, match="document version"):
        DOCXLocatorSegment.model_validate(
            _paragraph_locator(document_version_id="  ")
        )


@pytest.mark.parametrize(
    "structural_metadata",
    [
        None,
        [{"element_type": "Paragraph", "element_index": 2}],
        {"format": "docx", "section_path": ["Overview"]},
    ],
)
def test_existing_structural_metadata_remains_backward_compatible(
    structural_metadata,
):
    result = SearchResult(
        source_ref="S1",
        chunk_id="chunk-1",
        document_id="document-1",
        filename="sample.docx",
        page_number=1,
        content="A cited passage.",
        structural_metadata=structural_metadata,
        bbox=[],
    )

    assert result.structural_metadata == structural_metadata
