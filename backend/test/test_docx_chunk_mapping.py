from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree

import pytest

from app.models.schema import DOCXLocatorSegment
from app.services.docx_alignment import align_docx_elements
from app.services.docx_chunk_mapping import (
    DOCXChunkMappingError,
    map_chunks_to_docx_locators,
)
from app.services.docx_ooxml_index import build_docx_ooxml_index


_VERSION = "version-1"


def _paragraph_record(index, text):
    return {
        "element_type": "paragraph",
        "text": text,
        "text_length": len(text),
        "paragraph_index": index,
        "structural_path": [{"kind": "paragraph", "index": index}],
    }


def _table_record(cells):
    table_path = [{"kind": "table", "index": 0}]
    rows = []
    for row_index, row_values in enumerate(cells):
        row = {"row_index": row_index, "cells": []}
        for cell_index, paragraph_texts in enumerate(row_values):
            cell_path = table_path + [
                {"kind": "row", "index": row_index},
                {"kind": "cell", "index": cell_index},
            ]
            paragraphs = []
            for cell_paragraph_index, text in enumerate(paragraph_texts):
                paragraphs.append(
                    {
                        "element_type": "table_cell_paragraph",
                        "text": text,
                        "text_length": len(text),
                        "paragraph_index": cell_paragraph_index,
                        "cell_paragraph_index": cell_paragraph_index,
                        "structural_path": cell_path
                        + [
                            {
                                "kind": "paragraph",
                                "index": cell_paragraph_index,
                            }
                        ],
                    }
                )
            row["cells"].append(
                {
                    "cell_index": cell_index,
                    "text": "\n".join(paragraph_texts),
                    "elements": paragraphs,
                }
            )
        rows.append(row)
    return {
        "element_type": "table",
        "table_index": 0,
        "structural_path": table_path,
        "rows": rows,
    }


def _index(*elements):
    return {"part_name": "word/document.xml", "elements": list(elements)}


def _paragraph_locator(index, text, start=0, end=None):
    if end is None:
        end = len(text)
    return DOCXLocatorSegment.model_validate(
        {
            "document_version_id": _VERSION,
            "element_type": "paragraph",
            "structural_path": [{"kind": "paragraph", "index": index}],
            "paragraph_index": index,
            "text_range": {"start": start, "end": end},
            "section_path": [],
            "mapping_status": "resolved",
        }
    ).model_dump(mode="json")


def _cell_locator(
    row,
    cell,
    paragraph,
    text,
    start=0,
    end=None,
):
    if end is None:
        end = len(text)
    return DOCXLocatorSegment.model_validate(
        {
            "document_version_id": _VERSION,
            "element_type": "table_cell_paragraph",
            "structural_path": [
                {"kind": "table", "index": 0},
                {"kind": "row", "index": row},
                {"kind": "cell", "index": cell},
                {"kind": "paragraph", "index": paragraph},
            ],
            "paragraph_index": paragraph,
            "table_index": 0,
            "row_index": row,
            "cell_index": cell,
            "cell_paragraph_index": paragraph,
            "text_range": {"start": start, "end": end},
            "section_path": [],
            "mapping_status": "resolved",
        }
    ).model_dump(mode="json")


def _alignment(index, text, locators, status="resolved"):
    return {
        "element_index": index,
        "element_type": "NarrativeText",
        "original_text": text,
        "alignment_status": status,
        "locator_segments": locators,
        "candidate_paths": [],
        "candidate_text_ranges": [],
        "alignment_reason": "test fixture",
    }


def _chunk(text, index, start, end, **metadata):
    source = {
        "element_index": index,
        "text_range": {"start": start, "end": end},
    }
    source.update(metadata)
    return {"id": f"chunk-{index}-{start}", "text": text, "provenance": [source]}


def _map(chunks, alignments, structural_index):
    return map_chunks_to_docx_locators(
        chunks,
        alignments,
        structural_index,
        _VERSION,
    )


def test_maps_single_paragraph_and_preserves_version_identity():
    text = "Cited paragraph."
    result = _map(
        [_chunk(text, 0, 0, len(text))],
        [_alignment(0, text, [_paragraph_locator(0, text)])],
        _index(_paragraph_record(0, text)),
    )[0]

    assert result["mapping_status"] == "resolved"
    assert result["original_chunk_text"] == text
    assert result["document_version_id"] == _VERSION
    assert result["locator_segments"][0]["text_range"] == {
        "start": 0,
        "end": len(text),
    }


def test_maps_one_chunk_across_multiple_paragraphs():
    first, second = "First.", "Second."
    extracted = f"{first} {second}"
    result = _map(
        [_chunk(extracted, 0, 0, len(extracted))],
        [
            _alignment(
                0,
                extracted,
                [
                    _paragraph_locator(0, first),
                    _paragraph_locator(1, second),
                ],
            )
        ],
        _index(_paragraph_record(0, first), _paragraph_record(1, second)),
    )[0]

    assert result["mapping_status"] == "resolved"
    assert [segment["structural_path"][0]["index"] for segment in result["locator_segments"]] == [0, 1]


def test_maps_multiple_chunk_ranges_and_overlaps_independently():
    text = "abcdefghij"
    alignment = [_alignment(0, text, [_paragraph_locator(0, text)])]
    structural_index = _index(_paragraph_record(0, text))
    chunks = [
        _chunk(text[:6], 0, 0, 6),
        _chunk(text[4:], 0, 4, 10),
    ]

    results = _map(chunks, alignment, structural_index)

    assert [
        result["locator_segments"][0]["text_range"]
        for result in results
    ] == [{"start": 0, "end": 6}, {"start": 4, "end": 10}]


def test_translates_ranges_after_whitespace_normalization():
    extracted = "Left   right"
    canonical = "Left right"
    result = _map(
        [_chunk("right", 0, 7, 12)],
        [_alignment(0, extracted, [_paragraph_locator(0, canonical)])],
        _index(_paragraph_record(0, canonical)),
    )[0]

    assert result["mapping_status"] == "resolved"
    assert result["locator_segments"][0]["text_range"] == {
        "start": 5,
        "end": 10,
    }


def test_reports_ambiguous_when_chunk_boundary_splits_collapsed_whitespace():
    extracted = "Left   right"
    canonical = "Left right"
    result = _map(
        [_chunk(" ", 0, 4, 5)],
        [_alignment(0, extracted, [_paragraph_locator(0, canonical)])],
        _index(_paragraph_record(0, canonical)),
    )[0]

    assert result["mapping_status"] == "unresolved"
    assert result["locator_segments"] == []
    assert "splits a whitespace run" in result["diagnostics"][0]


def test_preserves_tab_line_break_and_unicode_offsets():
    text = "a\tb\nCafé 🧠"
    start = text.index("🧠")
    result = _map(
        [_chunk("🧠", 0, start, start + 1)],
        [_alignment(0, text, [_paragraph_locator(0, text)])],
        _index(_paragraph_record(0, text)),
    )[0]

    assert result["mapping_status"] == "resolved"
    assert result["locator_segments"][0]["text_range"] == {
        "start": start,
        "end": start + 1,
    }


def test_maps_table_cell_ranges_using_flattened_table_offsets():
    table_html = "<table><tr><td>A</td><td>Bee</td></tr></table>"
    result = _map(
        [
            _chunk(
                "Bee",
                0,
                4,
                7,
                element_type="Table",
                table_html=table_html,
            )
        ],
        [
            _alignment(
                0,
                "A | Bee",
                [
                    _cell_locator(0, 0, 0, "A"),
                    _cell_locator(0, 1, 0, "Bee"),
                ],
            )
        ],
        _index(
            _table_record(
                [[["A"], ["Bee"]]],
            )
        ),
    )[0]

    assert result["mapping_status"] == "resolved"
    segment = result["locator_segments"][0]
    assert segment["cell_index"] == 1
    assert segment["text_range"] == {"start": 0, "end": 3}


def test_maps_multiple_paragraphs_in_a_cell_and_skips_empty_cells():
    table_html = (
        "<table><tr><td></td><td>First<br/>Second</td></tr></table>"
    )
    result = _map(
        [
            _chunk(
                "Second",
                0,
                6,
                12,
                element_type="Table",
                table_html=table_html,
            )
        ],
        [
            _alignment(
                0,
                "First Second",
                [
                    _cell_locator(0, 1, 0, "First"),
                    _cell_locator(0, 1, 1, "Second"),
                ],
            )
        ],
        _index(
            _table_record(
                [[[], ["First", "Second"]]],
            )
        ),
    )[0]

    assert result["mapping_status"] == "resolved"
    assert len(result["locator_segments"]) == 1
    assert result["locator_segments"][0]["cell_paragraph_index"] == 1
    assert result["locator_segments"][0]["text_range"] == {
        "start": 0,
        "end": 6,
    }


def test_maps_flattened_table_text_when_empty_cells_are_omitted():
    table_html = (
        "<table><tr><td>One</td><td></td><td>Three</td></tr></table>"
    )
    result = _map(
        [
            _chunk(
                "Three",
                0,
                6,
                11,
                element_type="Table",
                table_html=table_html,
            )
        ],
        [
            _alignment(
                0,
                "One | Three",
                [
                    _cell_locator(0, 0, 0, "One"),
                    _cell_locator(0, 2, 0, "Three"),
                ],
            )
        ],
        _index(_table_record([[["One"], [], ["Three"]]])),
    )[0]

    assert result["mapping_status"] == "resolved"
    assert result["locator_segments"][0]["cell_index"] == 2
    assert result["locator_segments"][0]["text_range"] == {
        "start": 0,
        "end": 5,
    }


@pytest.mark.parametrize(
    ("alignment_status", "expected_status"),
    [("ambiguous", "ambiguous"), ("unresolved", "unresolved")],
)
def test_does_not_promote_ambiguous_or_unresolved_alignment(
    alignment_status,
    expected_status,
):
    result = _map(
        [_chunk("text", 0, 0, 4)],
        [_alignment(0, "text", [], alignment_status)],
        _index(_paragraph_record(0, "text")),
    )[0]

    assert result["mapping_status"] == expected_status
    assert result["locator_segments"] == []


def test_rejects_malformed_half_open_provenance_range():
    with pytest.raises(DOCXChunkMappingError, match="half-open range"):
        _map(
            [_chunk("text", 0, 2, 2)],
            [_alignment(0, "text", [_paragraph_locator(0, "text")])],
            _index(_paragraph_record(0, "text")),
        )


def test_rejects_malformed_ooxml_index():
    with pytest.raises(DOCXChunkMappingError, match="paragraph records"):
        _map(
            [_chunk("text", 0, 0, 4)],
            [_alignment(0, "text", [_paragraph_locator(0, "text")])],
            _index(
                {
                    "element_type": "paragraph",
                    "structural_path": [{"kind": "paragraph", "index": 0}],
                }
            ),
        )


def test_out_of_bounds_source_or_canonical_ranges_remain_unresolved():
    source_result = _map(
        [_chunk("text", 0, 0, 6)],
        [_alignment(0, "text", [_paragraph_locator(0, "text")])],
        _index(_paragraph_record(0, "text")),
    )[0]
    invalid_locator = _paragraph_locator(0, "text", 0, 5)
    invalid_locator["text_range"] = {"start": 0, "end": 99}
    canonical_result = _map(
        [_chunk("text", 0, 0, 4)],
        [_alignment(0, "text", [invalid_locator])],
        _index(_paragraph_record(0, "text")),
    )[0]

    assert source_result["mapping_status"] == "unresolved"
    assert canonical_result["mapping_status"] == "unresolved"
    assert source_result["locator_segments"] == []
    assert canonical_result["locator_segments"] == []


def test_chunk_spanning_multiple_provenance_elements_is_mapped_in_order():
    first, second = "First", "Second"
    chunks = [
        {
            "id": "combined",
            "text": "First Second",
            "provenance": [
                {"element_index": 0, "text_range": {"start": 0, "end": 5}},
                {"element_index": 1, "text_range": {"start": 0, "end": 6}},
            ],
        }
    ]
    results = _map(
        chunks,
        [
            _alignment(0, first, [_paragraph_locator(0, first)]),
            _alignment(1, second, [_paragraph_locator(1, second)]),
        ],
        _index(_paragraph_record(0, first), _paragraph_record(1, second)),
    )

    assert results[0]["mapping_status"] == "resolved"
    assert [
        segment["structural_path"][0]["index"]
        for segment in results[0]["locator_segments"]
    ] == [0, 1]


def test_mapping_results_are_deterministic():
    text = "stable"
    args = (
        [_chunk(text, 0, 0, len(text))],
        [_alignment(0, text, [_paragraph_locator(0, text)])],
        _index(_paragraph_record(0, text)),
    )

    assert _map(*args) == _map(*args)


def test_maps_actual_alignment_and_ooxml_index_output():
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    word = f"{{{namespace}}}"
    document = ElementTree.Element(f"{word}document")
    body = ElementTree.SubElement(document, f"{word}body")
    paragraph = ElementTree.SubElement(body, f"{word}p")
    run = ElementTree.SubElement(paragraph, f"{word}r")
    ElementTree.SubElement(run, f"{word}t").text = "Exact sentence."

    docx = BytesIO()
    with ZipFile(docx, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            ElementTree.tostring(document, encoding="utf-8"),
        )
    structural_index = build_docx_ooxml_index(docx.getvalue())
    extraction_element = SimpleNamespace(
        category="NarrativeText",
        text="  Exact sentence.  ",
        id="element-1",
        metadata=SimpleNamespace(),
    )
    alignments = align_docx_elements(
        [extraction_element],
        structural_index,
        _VERSION,
    )

    result = map_chunks_to_docx_locators(
        [
            {
                "id": "chunk-1",
                "text": "Exact sentence.",
                "provenance": [
                    {
                        "element_index": 0,
                        "text_range": {"start": 0, "end": 15},
                    }
                ],
            }
        ],
        alignments,
        structural_index,
        _VERSION,
    )[0]

    assert result["mapping_status"] == "resolved"
    assert result["locator_segments"][0]["structural_path"] == [
        {"kind": "paragraph", "index": 0}
    ]


def test_maps_actual_table_alignment_with_table_html_provenance():
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    word = f"{{{namespace}}}"
    document = ElementTree.Element(f"{word}document")
    body = ElementTree.SubElement(document, f"{word}body")
    table = ElementTree.SubElement(body, f"{word}tbl")
    row = ElementTree.SubElement(table, f"{word}tr")
    for cell_text in ("A", "Bee"):
        cell = ElementTree.SubElement(row, f"{word}tc")
        paragraph = ElementTree.SubElement(cell, f"{word}p")
        run = ElementTree.SubElement(paragraph, f"{word}r")
        ElementTree.SubElement(run, f"{word}t").text = cell_text

    docx = BytesIO()
    with ZipFile(docx, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            ElementTree.tostring(document, encoding="utf-8"),
        )
    structural_index = build_docx_ooxml_index(docx.getvalue())
    table_html = "<table><tr><td>A</td><td>Bee</td></tr></table>"
    extraction_element = SimpleNamespace(
        category="Table",
        text="A | Bee",
        id="table-1",
        metadata=SimpleNamespace(text_as_html=table_html),
    )
    alignments = align_docx_elements(
        [extraction_element],
        structural_index,
        _VERSION,
    )

    result = map_chunks_to_docx_locators(
        [
            {
                "id": "table-chunk",
                "text": "Bee",
                "provenance": [
                    {
                        "element_index": 0,
                        "element_type": "Table",
                        "table_html": table_html,
                        "text_range": {"start": 4, "end": 7},
                    }
                ],
            }
        ],
        alignments,
        structural_index,
        _VERSION,
    )[0]

    assert alignments[0]["alignment_status"] == "resolved"
    assert result["mapping_status"] == "resolved"
    assert result["locator_segments"][0]["cell_index"] == 1
    assert result["locator_segments"][0]["text_range"] == {
        "start": 0,
        "end": 3,
    }
