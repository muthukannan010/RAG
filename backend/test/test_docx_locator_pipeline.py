"""End-to-end tests for the standalone DOCX locator pipeline.

Locator ranges are Python Unicode code-point offsets. Browser string APIs use
UTF-16 code units; before highlighting, convert each endpoint with
``len(text[:offset].encode("utf-16-le")) // 2``.
"""

from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree

import pytest

from app.models.schema import DOCXLocatorSegment
from app.services.docx_alignment import align_docx_elements
from app.services.docx_chunk_mapping import map_chunks_to_docx_locators
from app.services.docx_ooxml_index import build_docx_ooxml_index


_WORD_NS = (
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
)
_W = f"{{{_WORD_NS}}}"
_VERSION = "fixture-version-1"
ElementTree.register_namespace("w", _WORD_NS)


def _paragraph(*parts):
    paragraph = ElementTree.Element(f"{_W}p")
    for part in parts:
        if part == "\t":
            run = ElementTree.SubElement(paragraph, f"{_W}r")
            ElementTree.SubElement(run, f"{_W}tab")
        elif part == "\n":
            run = ElementTree.SubElement(paragraph, f"{_W}r")
            ElementTree.SubElement(run, f"{_W}br")
        else:
            run = ElementTree.SubElement(paragraph, f"{_W}r")
            ElementTree.SubElement(run, f"{_W}t").text = part
    return paragraph


def _cell(*children):
    cell = ElementTree.Element(f"{_W}tc")
    for child in children:
        cell.append(child)
    return cell


def _table(rows):
    table = ElementTree.Element(f"{_W}tbl")
    for cells in rows:
        row = ElementTree.SubElement(table, f"{_W}tr")
        for cell_elements in cells:
            row.append(_cell(*cell_elements))
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


def _extraction(
    text,
    category="NarrativeText",
    *,
    element_id=None,
    parent_id=None,
    category_depth=None,
    table_html=None,
):
    return SimpleNamespace(
        category=category,
        text=text,
        id=element_id,
        metadata=SimpleNamespace(
            parent_id=parent_id,
            category_depth=category_depth,
            text_as_html=table_html,
        ),
    )


def _pipeline(body_elements, extraction_elements, chunks):
    docx = _docx_bytes(*body_elements)
    index = build_docx_ooxml_index(docx)
    alignments = align_docx_elements(
        extraction_elements,
        index,
        _VERSION,
    )
    mapped = map_chunks_to_docx_locators(
        chunks,
        alignments,
        index,
        _VERSION,
    )
    return docx, index, alignments, mapped


def _chunk(chunk_id, text, provenance):
    return {
        "id": chunk_id,
        "chunk_index": int(chunk_id.rsplit("-", 1)[-1])
        if chunk_id.rsplit("-", 1)[-1].isdigit()
        else 0,
        "page_number": 1,
        "text": text,
        "bbox": [],
        "provenance": provenance,
    }


def _source(element_index, start, end, **metadata):
    return {
        "element_index": element_index,
        "text_range": {"start": start, "end": end},
        **metadata,
    }


def _paragraph_records(index):
    records = {}

    def visit(table):
        for row in table["rows"]:
            for cell in row["cells"]:
                for element in cell["elements"]:
                    if element["element_type"] == "table":
                        visit(element)
                    else:
                        records[
                            tuple(
                                (step["kind"], step["index"])
                                for step in element["structural_path"]
                            )
                        ] = element

    for element in index["elements"]:
        if element["element_type"] == "table":
            visit(element)
        else:
            records[
                tuple(
                    (step["kind"], step["index"])
                    for step in element["structural_path"]
                )
            ] = element
    return records


def _resolved_text(index, locator):
    validated = DOCXLocatorSegment.model_validate(locator)
    assert validated.is_verified
    path = tuple(
        (step.kind, step.index)
        for step in validated.structural_path
    )
    record = _paragraph_records(index)[path]
    assert record["element_type"] == validated.element_type
    assert 0 <= validated.text_range.start < validated.text_range.end
    assert validated.text_range.end <= len(record["text"])
    return record["text"][
        validated.text_range.start:validated.text_range.end
    ]


def _assert_resolved_targets_are_valid(index, mapped):
    for result in mapped:
        assert result["mapping_status"] == "resolved"
        assert result["locator_segments"]
        for locator in result["locator_segments"]:
            assert _resolved_text(index, locator)


def _collapse_whitespace(text):
    return " ".join(text.split())


def test_end_to_end_single_paragraph_split_runs_and_exact_chunk_text():
    text = "A citation across runs."
    extraction = _extraction(text)
    source_start, source_end = 2, 11
    chunk_text = text[source_start:source_end]

    _, index, alignments, mapped = _pipeline(
        [_paragraph("A citation ", "across runs.")],
        [extraction],
        [
            _chunk(
                "chunk-0",
                chunk_text,
                [_source(0, source_start, source_end)],
            )
        ],
    )

    assert alignments[0]["alignment_status"] == "resolved"
    _assert_resolved_targets_are_valid(index, mapped)
    assert _resolved_text(index, mapped[0]["locator_segments"][0]) == chunk_text
    assert mapped[0]["original_chunk_text"] == chunk_text


def test_end_to_end_overlapping_chunks_keep_independent_ranges():
    text = "0123456789"
    _, index, _, mapped = _pipeline(
        [_paragraph(text)],
        [_extraction(text)],
        [
            _chunk("chunk-0", text[:6], [_source(0, 0, 6)]),
            _chunk("chunk-1", text[4:], [_source(0, 4, 10)]),
        ],
    )

    _assert_resolved_targets_are_valid(index, mapped)
    assert [
        _resolved_text(index, result["locator_segments"][0])
        for result in mapped
    ] == [text[:6], text[4:]]
    assert [result["original_chunk_text"] for result in mapped] == [
        text[:6],
        text[4:],
    ]


def test_end_to_end_single_chunk_spanning_multiple_paragraphs():
    first = "First paragraph."
    second = "Second paragraph."
    extracted_text = f"{first}\n{second}"
    chunk_text = f"{first} {second}"

    _, index, alignments, mapped = _pipeline(
        [_paragraph(first), _paragraph(second)],
        [_extraction(extracted_text)],
        [
            _chunk(
                "chunk-0",
                chunk_text,
                [_source(0, 0, len(extracted_text))],
            )
        ],
    )

    assert alignments[0]["alignment_status"] == "resolved"
    _assert_resolved_targets_are_valid(index, mapped)
    selected = [
        _resolved_text(index, locator)
        for locator in mapped[0]["locator_segments"]
    ]
    assert selected == [first, second]
    assert _collapse_whitespace(" ".join(selected)) == chunk_text


def test_end_to_end_repeated_paragraphs_use_heading_context():
    elements = [
        _extraction(
            "Section A",
            "Title",
            element_id="heading-a",
            category_depth=0,
        ),
        _extraction("Repeated passage.", parent_id="heading-a"),
        _extraction(
            "Section B",
            "Title",
            element_id="heading-b",
            category_depth=0,
        ),
        _extraction("Repeated passage.", parent_id="heading-b"),
    ]
    body = [
        _paragraph("Section A"),
        _paragraph("Repeated passage."),
        _paragraph("Section B"),
        _paragraph("Repeated passage."),
    ]
    chunks = [
        _chunk(
            "chunk-1",
            "Repeated passage.",
            [_source(1, 0, len("Repeated passage."))],
        ),
        _chunk(
            "chunk-3",
            "Repeated passage.",
            [_source(3, 0, len("Repeated passage."))],
        ),
    ]

    _, index, alignments, mapped = _pipeline(body, elements, chunks)

    assert [item["alignment_status"] for item in alignments] == [
        "resolved",
        "resolved",
        "resolved",
        "resolved",
    ]
    assert alignments[1]["locator_segments"][0]["section_path"] == ["Section A"]
    assert alignments[3]["locator_segments"][0]["section_path"] == ["Section B"]
    _assert_resolved_targets_are_valid(index, mapped)
    assert [
        result["locator_segments"][0]["structural_path"][0]["index"]
        for result in mapped
    ] == [1, 3]
    assert [
        _resolved_text(index, result["locator_segments"][0])
        for result in mapped
    ] == ["Repeated passage.", "Repeated passage."]


def test_end_to_end_tabs_linebreaks_and_supplementary_unicode_offsets():
    canonical = "Run\tbefore\nEmoji 🧠 after"
    extraction_text = "Run before Emoji 🧠 after"
    python_start = canonical.index("🧠")
    python_end = python_start + 1
    _, index, alignments, mapped = _pipeline(
        [
            _paragraph(
                "Run",
                "\t",
                "before",
                "\n",
                "Emoji ",
                "🧠",
                " after",
            )
        ],
        [_extraction(extraction_text)],
        [
            _chunk(
                "chunk-0",
                "🧠",
                [_source(0, extraction_text.index("🧠"), extraction_text.index("🧠") + 1)],
            )
        ],
    )

    assert alignments[0]["alignment_status"] == "resolved"
    _assert_resolved_targets_are_valid(index, mapped)
    locator = mapped[0]["locator_segments"][0]
    assert locator["text_range"] == {
        "start": python_start,
        "end": python_end,
    }
    assert _resolved_text(index, locator) == "🧠"

    # For "Run\tbefore\nEmoji 🧠", Python counts the emoji as one code point;
    # JavaScript UTF-16 offsets count it as a surrogate pair (two code units).
    utf16_start = len(canonical[:python_start].encode("utf-16-le")) // 2
    utf16_end = len(canonical[:python_end].encode("utf-16-le")) // 2
    assert (python_start, python_end) == (17, 18)
    assert (utf16_start, utf16_end) == (17, 19)


def test_end_to_end_table_rows_cells_empty_cells_and_cell_paragraphs():
    table_html = (
        "<table>"
        "<tr><td>A</td><td></td><td>B</td></tr>"
        "<tr><td>First<br/>Second</td><td>D</td></tr>"
        "</table>"
    )
    extracted_table_text = "A | B\nFirst Second | D"
    body_table = _table(
        [
            [
                [_paragraph("A")],
                [],
                [_paragraph("B")],
            ],
            [
                [_paragraph("First"), _paragraph("Second")],
                [_paragraph("D")],
            ],
        ]
    )
    extraction = _extraction(
        extracted_table_text,
        "Table",
        table_html=table_html,
    )
    start = extracted_table_text.index("Second")
    end = start + len("Second")
    chunks = [
        _chunk(
            "chunk-0",
            "Second",
            [
                _source(
                    0,
                    start,
                    end,
                    element_type="Table",
                    table_html=table_html,
                )
            ],
        ),
        _chunk(
            "chunk-1",
            "B",
            [
                _source(
                    0,
                    extracted_table_text.index("B"),
                    extracted_table_text.index("B") + 1,
                    element_type="Table",
                    table_html=table_html,
                )
            ],
        ),
    ]

    _, index, alignments, mapped = _pipeline(
        [body_table],
        [extraction],
        chunks,
    )

    assert alignments[0]["alignment_status"] == "resolved"
    _assert_resolved_targets_are_valid(index, mapped)
    second_locator = mapped[0]["locator_segments"][0]
    assert second_locator["row_index"] == 1
    assert second_locator["cell_index"] == 0
    assert second_locator["cell_paragraph_index"] == 1
    assert _resolved_text(index, second_locator) == "Second"
    empty_cell_locator = mapped[1]["locator_segments"][0]
    assert empty_cell_locator["cell_index"] == 2
    assert _resolved_text(index, empty_cell_locator) == "B"
    assert [result["original_chunk_text"] for result in mapped] == [
        "Second",
        "B",
    ]


def test_end_to_end_nested_table_paragraph_has_verified_nested_path():
    nested = _table([[[_paragraph("Nested citation.")]]])
    outer = _table(
        [
            [
                [
                    _paragraph("Outer content."),
                    nested,
                ]
            ]
        ]
    )
    text = "Nested citation."
    _, index, alignments, mapped = _pipeline(
        [outer],
        [_extraction(text)],
        [
            _chunk(
                "chunk-0",
                text,
                [_source(0, 0, len(text))],
            )
        ],
    )

    assert alignments[0]["alignment_status"] == "resolved"
    _assert_resolved_targets_are_valid(index, mapped)
    locator = mapped[0]["locator_segments"][0]
    assert locator["element_type"] == "table_cell_paragraph"
    assert [
        (step["kind"], step["index"])
        for step in locator["structural_path"]
    ] == [
        ("table", 0),
        ("row", 0),
        ("cell", 0),
        ("table", 0),
        ("row", 0),
        ("cell", 0),
        ("paragraph", 0),
    ]
    assert _resolved_text(index, locator) == text


@pytest.mark.parametrize(
    ("source_text", "paragraphs", "expected_status"),
    [
        (
            "Repeated.",
            [_paragraph("Repeated."), _paragraph("Repeated.")],
            "ambiguous",
        ),
        (
            "Not in the original.",
            [_paragraph("Original text.")],
            "unresolved",
        ),
    ],
)
def test_end_to_end_ambiguous_and_unresolved_never_become_verified(
    source_text,
    paragraphs,
    expected_status,
):
    _, _, alignments, mapped = _pipeline(
        paragraphs,
        [_extraction(source_text)],
        [
            _chunk(
                "chunk-0",
                source_text,
                [_source(0, 0, len(source_text))],
            )
        ],
    )

    assert alignments[0]["alignment_status"] == expected_status
    assert alignments[0]["locator_segments"] == []
    assert mapped[0]["mapping_status"] == expected_status
    assert mapped[0]["locator_segments"] == []


def test_end_to_end_out_of_range_provenance_remains_unresolved():
    text = "Short text."
    _, _, alignments, mapped = _pipeline(
        [_paragraph(text)],
        [_extraction(text)],
        [
            _chunk(
                "chunk-0",
                "not the source text",
                [_source(0, 0, len(text) + 1)],
            )
        ],
    )

    assert alignments[0]["alignment_status"] == "resolved"
    assert mapped[0]["mapping_status"] == "unresolved"
    assert mapped[0]["locator_segments"] == []
    assert mapped[0]["original_chunk_text"] == "not the source text"


def test_end_to_end_repeated_execution_is_deterministic():
    body = [
        _paragraph("Section"),
        _paragraph("Stable citation."),
    ]
    elements = [
        _extraction(
            "Section",
            "Title",
            element_id="heading",
            category_depth=0,
        ),
        _extraction("Stable citation.", parent_id="heading"),
    ]
    chunks = [
        _chunk(
            "chunk-0",
            "Stable citation.",
            [_source(1, 0, len("Stable citation."))],
        )
    ]

    first = _pipeline(body, elements, chunks)
    second = _pipeline(body, elements, chunks)

    assert first[1:] == second[1:]
