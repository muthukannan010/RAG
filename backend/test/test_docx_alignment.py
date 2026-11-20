from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree

import pytest

from app.services.docx_alignment import (
    DOCXAlignmentError,
    align_docx_elements,
)
from app.services.docx_ooxml_index import build_docx_ooxml_index


_WORD_NS = (
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
)
_W = f"{{{_WORD_NS}}}"
ElementTree.register_namespace("w", _WORD_NS)


def _paragraph(text):
    paragraph = ElementTree.Element(f"{_W}p")
    run = ElementTree.SubElement(paragraph, f"{_W}r")
    ElementTree.SubElement(run, f"{_W}t").text = text
    return paragraph


def _table(rows):
    table = ElementTree.Element(f"{_W}tbl")
    for row_values in rows:
        row = ElementTree.SubElement(table, f"{_W}tr")
        for value in row_values:
            cell = ElementTree.SubElement(row, f"{_W}tc")
            if value is not None:
                cell.append(_paragraph(value))
    return table


def _docx_bytes(*body_elements):
    document = ElementTree.Element(f"{_W}document")
    body = ElementTree.SubElement(document, f"{_W}body")
    for element in body_elements:
        body.append(element)

    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            ElementTree.tostring(
                document,
                encoding="utf-8",
                xml_declaration=True,
            ),
        )
    return output.getvalue()


def _element(
    text,
    category="NarrativeText",
    *,
    element_id=None,
    parent_id=None,
    category_depth=None,
    text_as_html=None,
    section_path=None,
):
    metadata = SimpleNamespace(
        parent_id=parent_id,
        category_depth=category_depth,
        text_as_html=text_as_html,
        section_path=section_path,
    )
    return SimpleNamespace(
        category=category,
        text=text,
        id=element_id,
        metadata=metadata,
    )


def _align(elements, *body_elements):
    index = build_docx_ooxml_index(_docx_bytes(*body_elements))
    return align_docx_elements(elements, index, "version-1")


def test_exact_paragraph_match_preserves_original_extraction_text():
    extracted_text = "  Exact\tparagraph text.  "
    result = _align(
        [_element(extracted_text)],
        _paragraph("Exact paragraph text."),
    )[0]

    assert result["alignment_status"] == "resolved"
    assert result["original_text"] == extracted_text
    assert result["locator_segments"][0]["structural_path"] == [
        {"kind": "paragraph", "index": 0}
    ]
    assert result["locator_segments"][0]["text_range"] == {
        "start": 0,
        "end": len("Exact paragraph text."),
    }


def test_repeated_paragraphs_resolve_in_document_order():
    elements = [
        _element("Repeated text."),
        _element("Middle paragraph."),
        _element("Repeated text."),
    ]
    results = _align(
        elements,
        _paragraph("Repeated text."),
        _paragraph("Middle paragraph."),
        _paragraph("Repeated text."),
    )

    assert [result["alignment_status"] for result in results] == [
        "resolved",
        "resolved",
        "resolved",
    ]
    assert [
        result["locator_segments"][0]["structural_path"][0]["index"]
        for result in results
    ] == [0, 1, 2]


def test_section_context_disambiguates_repeated_text():
    elements = [
        _element(
            "Section A",
            "Title",
            element_id="heading-a",
            category_depth=0,
        ),
        _element("same", parent_id="heading-a"),
        _element(
            "Section B",
            "Title",
            element_id="heading-b",
            category_depth=0,
        ),
        _element("same", parent_id="heading-b"),
    ]
    results = _align(
        elements,
        _paragraph("Section A"),
        _paragraph("same"),
        _paragraph("Section B"),
        _paragraph("same"),
    )

    assert [item["alignment_status"] for item in results] == [
        "resolved",
        "resolved",
        "resolved",
        "resolved",
    ]
    assert [
        item["locator_segments"][0]["structural_path"][0]["index"]
        for item in (results[1], results[3])
    ] == [1, 3]
    assert results[1]["locator_segments"][0]["section_path"] == [
        "Section A"
    ]
    assert results[3]["locator_segments"][0]["section_path"] == [
        "Section B"
    ]


def test_paragraph_split_across_extraction_elements_maps_ranges():
    results = _align(
        [_element("Alpha "), _element("Beta")],
        _paragraph("Alpha Beta"),
    )

    assert [result["alignment_status"] for result in results] == [
        "resolved",
        "resolved",
    ]
    assert [
        result["locator_segments"][0]["text_range"]
        for result in results
    ] == [{"start": 0, "end": 5}, {"start": 6, "end": 10}]


def test_one_extraction_element_can_map_multiple_paragraphs_and_cells():
    results = _align(
        [_element("First paragraph\nSecond paragraph")],
        _paragraph("First paragraph"),
        _table([["Second paragraph"]]),
    )

    segments = results[0]["locator_segments"]
    assert results[0]["alignment_status"] == "resolved"
    assert [segment["element_type"] for segment in segments] == [
        "paragraph",
        "table_cell_paragraph",
    ]
    assert [
        segment["text_range"]
        for segment in segments
    ] == [
        {"start": 0, "end": len("First paragraph")},
        {"start": 0, "end": len("Second paragraph")},
    ]


def test_repeated_text_without_enough_context_is_ambiguous():
    result = _align(
        [_element("Repeated.")],
        _paragraph("Repeated."),
        _paragraph("Other."),
        _paragraph("Repeated."),
    )[0]

    assert result["alignment_status"] == "ambiguous"
    assert result["locator_segments"] == []
    assert result["candidate_paths"] == [
        [{"kind": "paragraph", "index": 0}],
        [{"kind": "paragraph", "index": 2}],
    ]


def test_nonmatching_text_is_unresolved():
    result = _align(
        [_element("Not present in the document.")],
        _paragraph("Existing content."),
    )[0]

    assert result["alignment_status"] == "unresolved"
    assert result["locator_segments"] == []
    assert result["candidate_paths"] == []


def test_html_table_matches_row_and_cell_sequence():
    table_html = (
        "<table><tr><td>A</td><td>B</td></tr>"
        "<tr><td>C</td><td>D</td></tr></table>"
    )
    result = _align(
        [
            _element(
                "A | B\nC | D",
                "Table",
                text_as_html=table_html,
            )
        ],
        _table([["A", "B"], ["C", "D"]]),
    )[0]

    assert result["alignment_status"] == "resolved"
    assert len(result["locator_segments"]) == 4
    assert [
        (
            segment["table_index"],
            segment["row_index"],
            segment["cell_index"],
            segment["cell_paragraph_index"],
        )
        for segment in result["locator_segments"]
    ] == [
        (0, 0, 0, 0),
        (0, 0, 1, 0),
        (0, 1, 0, 0),
        (0, 1, 1, 0),
    ]


def test_flattened_table_text_maps_cells_without_html_metadata():
    result = _align(
        [_element("A | B\nC | D", "Table")],
        _table([["A", "B"], ["C", "D"]]),
    )[0]

    assert result["alignment_status"] == "resolved"
    assert [
        segment["structural_path"][-2]["index"]
        for segment in result["locator_segments"]
    ] == [0, 1, 0, 1]


def test_flattened_table_text_accounts_for_empty_cells_omitted_by_extraction():
    result = _align(
        [_element("A | C", "Table")],
        _table([["A", None, "C"]]),
    )[0]

    assert result["alignment_status"] == "resolved"
    assert [
        segment["cell_index"] for segment in result["locator_segments"]
    ] == [0, 2]


def test_partial_table_extraction_maps_only_matching_row_cells():
    result = _align(
        [
            _element(
                "C | D",
                "Table",
                text_as_html="<table><tr><td>C</td><td>D</td></tr></table>",
            )
        ],
        _table([["A", "B"], ["C", "D"]]),
    )[0]

    assert result["alignment_status"] == "resolved"
    assert {
        segment["row_index"] for segment in result["locator_segments"]
    } == {1}
    assert {
        segment["cell_index"] for segment in result["locator_segments"]
    } == {0, 1}


def test_ambiguous_table_match_returns_candidate_paths_not_selected_locators():
    table = _table([["A", "B"]])
    result = _align(
        [
            _element(
                "A | B",
                "Table",
                text_as_html="<table><tr><td>A</td><td>B</td></tr></table>",
            )
        ],
        table,
        _table([["A", "B"]]),
    )[0]

    assert result["alignment_status"] == "ambiguous"
    assert result["locator_segments"] == []
    assert len(result["candidate_paths"]) == 4
    assert {
        path[0]["index"] for path in result["candidate_paths"]
    } == {0, 1}


def test_section_context_filters_table_matches():
    first_table = _table([["value"]])
    second_table = _table([["value"]])
    elements = [
        _element("Section A", "Title", element_id="a", category_depth=0),
        _element("value", "Table", parent_id="a", text_as_html=(
            "<table><tr><td>value</td></tr></table>"
        )),
        _element("Section B", "Title", element_id="b", category_depth=0),
        _element("value", "Table", parent_id="b", text_as_html=(
            "<table><tr><td>value</td></tr></table>"
        )),
    ]
    results = _align(
        elements,
        _paragraph("Section A"),
        first_table,
        _paragraph("Section B"),
        second_table,
    )

    assert results[1]["alignment_status"] == "resolved"
    assert results[3]["alignment_status"] == "resolved"
    assert results[1]["locator_segments"][0]["table_index"] == 0
    assert results[3]["locator_segments"][0]["table_index"] == 1


def test_alignment_is_deterministic_for_identical_inputs():
    elements = [
        _element("One."),
        _element("Two."),
    ]
    body = (_paragraph("One."), _paragraph("Two."))

    assert _align(elements, *body) == _align(elements, *body)


@pytest.mark.parametrize(
    "elements,index,version",
    [
        (None, {"part_name": "word/document.xml", "elements": []}, "v1"),
        (
            [_element(123)],
            {"part_name": "word/document.xml", "elements": []},
            "v1",
        ),
        ([], {}, "v1"),
        ([], {"part_name": "word/document.xml", "elements": "bad"}, "v1"),
        ([], {"part_name": "word/document.xml", "elements": []}, ""),
    ],
)
def test_invalid_alignment_inputs_raise(elements, index, version):
    with pytest.raises(DOCXAlignmentError):
        align_docx_elements(elements, index, version)
