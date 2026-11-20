from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree

import pytest

from app.models.schema import DOCXLocatorSegment
from app.services.docx_ooxml_index import (
    DOCXOOXMLIndexError,
    build_docx_ooxml_index,
)


_WORD_NS = (
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
)
_W = f"{{{_WORD_NS}}}"
ElementTree.register_namespace("w", _WORD_NS)


def _p(*items):
    paragraph = ElementTree.Element(f"{_W}p")
    for item in items:
        if isinstance(item, str):
            run = ElementTree.SubElement(paragraph, f"{_W}r")
            ElementTree.SubElement(run, f"{_W}t").text = item
        else:
            paragraph.append(item)
    return paragraph


def _run_with(*items):
    run = ElementTree.Element(f"{_W}r")
    for item in items:
        run.append(item)
    return run


def _text(value):
    element = ElementTree.Element(f"{_W}t")
    element.text = value
    return element


def _table(rows):
    table = ElementTree.Element(f"{_W}tbl")
    for row_cells in rows:
        row = ElementTree.SubElement(table, f"{_W}tr")
        for cell_elements in row_cells:
            cell = ElementTree.SubElement(row, f"{_W}tc")
            for element in cell_elements:
                cell.append(element)
    return table


def _docx_bytes(*body_elements):
    document = ElementTree.Element(f"{_W}document")
    body = ElementTree.SubElement(document, f"{_W}body")
    for element in body_elements:
        body.append(element)

    xml_bytes = ElementTree.tostring(
        document,
        encoding="utf-8",
        xml_declaration=True,
    )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml_bytes)
    return output.getvalue()


def _cell(table_record, row_index, cell_index):
    return table_record["rows"][row_index]["cells"][cell_index]


def test_indexes_top_level_paragraphs_and_repeated_text_in_order():
    docx = _docx_bytes(
        _p("Repeat me."),
        _p("Between paragraphs."),
        _p("Repeat me."),
    )

    index = build_docx_ooxml_index(docx)
    paragraphs = index["elements"]

    assert [item["text"] for item in paragraphs] == [
        "Repeat me.",
        "Between paragraphs.",
        "Repeat me.",
    ]
    assert [item["structural_path"] for item in paragraphs] == [
        [{"kind": "paragraph", "index": 0}],
        [{"kind": "paragraph", "index": 1}],
        [{"kind": "paragraph", "index": 2}],
    ]
    assert [item["paragraph_index"] for item in paragraphs] == [0, 1, 2]


def test_paragraph_text_concatenates_runs_tabs_and_line_breaks():
    paragraph = _p(
        _run_with(_text("Run "), _text("text")),
        _run_with(ElementTree.Element(f"{_W}tab"), _text("after tab")),
        _run_with(
            ElementTree.Element(f"{_W}br"),
            _text("after break"),
            ElementTree.Element(f"{_W}cr"),
            _text("after carriage return"),
        ),
    )

    record = build_docx_ooxml_index(_docx_bytes(paragraph))["elements"][0]

    assert record["text"] == (
        "Run text\tafter tab\nafter break\nafter carriage return"
    )
    assert record["text_length"] == len(record["text"])


def test_tables_keep_rows_cells_and_paragraphs_in_physical_order():
    table = _table(
        [
            [
                [_p("First paragraph"), _p("Second paragraph")],
                [],
            ],
            [
                [_p("Third paragraph")],
                [_p()],
            ],
        ]
    )

    table_record = build_docx_ooxml_index(_docx_bytes(table))[
        "elements"
    ][0]
    first_cell = _cell(table_record, 0, 0)
    empty_cell = _cell(table_record, 0, 1)
    second_row_empty_paragraph = _cell(table_record, 1, 1)

    assert table_record["table_index"] == 0
    assert table_record["structural_path"] == [
        {"kind": "table", "index": 0}
    ]
    table_locator = DOCXLocatorSegment(
        document_version_id="version-1",
        element_type="table",
        structural_path=table_record["structural_path"],
        table_index=table_record["table_index"],
        text_range={"start": 0, "end": len(table_record["text"])},
        mapping_status="resolved",
    )
    assert table_locator.is_verified
    assert [row["row_index"] for row in table_record["rows"]] == [0, 1]
    assert [cell["cell_index"] for cell in table_record["rows"][0]["cells"]] == [
        0,
        1,
    ]
    assert first_cell["text"] == "First paragraph\nSecond paragraph"
    assert [
        paragraph["cell_paragraph_index"]
        for paragraph in first_cell["elements"]
    ] == [0, 1]
    assert [
        paragraph["structural_path"]
        for paragraph in first_cell["elements"]
    ] == [
        [
            {"kind": "table", "index": 0},
            {"kind": "row", "index": 0},
            {"kind": "cell", "index": 0},
            {"kind": "paragraph", "index": 0},
        ],
        [
            {"kind": "table", "index": 0},
            {"kind": "row", "index": 0},
            {"kind": "cell", "index": 0},
            {"kind": "paragraph", "index": 1},
        ],
    ]
    assert empty_cell["text"] == ""
    assert empty_cell["elements"] == []
    assert second_row_empty_paragraph["elements"][0]["text"] == ""


def test_paragraphs_before_between_and_after_tables_keep_body_order():
    docx = _docx_bytes(
        _p("Before"),
        _table([[[_p("First table")]]]),
        _p("Between"),
        _table([[[_p("Second table")]]]),
        _p("After"),
    )

    index = build_docx_ooxml_index(docx)

    assert [
        item["element_type"] for item in index["elements"]
    ] == ["paragraph", "table", "paragraph", "table", "paragraph"]
    assert [
        item.get("paragraph_index", item.get("table_index"))
        for item in index["elements"]
    ] == [0, 0, 2, 1, 4]
    assert [
        item["paragraph_index"]
        for item in index["elements"]
        if item["element_type"] == "paragraph"
    ] == [0, 2, 4]


def test_nested_tables_are_indexed_recursively_with_contract_paths():
    nested_table = _table([[[_p("Nested cell")]]])
    outer_table = _table(
        [
            [
                [
                    _p("Outer cell"),
                    nested_table,
                    _p("After nested table"),
                ]
            ]
        ]
    )

    index = build_docx_ooxml_index(_docx_bytes(outer_table))
    table_record = index["elements"][0]
    cell_elements = _cell(table_record, 0, 0)["elements"]
    nested_record = cell_elements[1]
    nested_paragraph = _cell(nested_record, 0, 0)["elements"][0]

    assert [item["element_type"] for item in cell_elements] == [
        "table_cell_paragraph",
        "table",
        "table_cell_paragraph",
    ]
    assert table_record["table_index"] == 0
    assert nested_record["table_index"] == 1
    assert nested_record["structural_path"] == [
        {"kind": "table", "index": 0},
        {"kind": "row", "index": 0},
        {"kind": "cell", "index": 0},
        {"kind": "table", "index": 0},
    ]
    assert nested_paragraph["paragraph_index"] == 1
    assert nested_paragraph["structural_path"] == [
        {"kind": "table", "index": 0},
        {"kind": "row", "index": 0},
        {"kind": "cell", "index": 0},
        {"kind": "table", "index": 0},
        {"kind": "row", "index": 0},
        {"kind": "cell", "index": 0},
        {"kind": "paragraph", "index": 0},
    ]
    locator = DOCXLocatorSegment(
        document_version_id="version-1",
        element_type="table_cell_paragraph",
        structural_path=nested_paragraph["structural_path"],
        paragraph_index=nested_paragraph["paragraph_index"],
        table_index=nested_record["table_index"],
        row_index=0,
        cell_index=0,
        cell_paragraph_index=0,
        text_range={"start": 0, "end": len(nested_paragraph["text"])},
        mapping_status="resolved",
    )
    assert locator.is_verified
    assert index["unsupported_structures"] == []


def test_unsupported_body_wrappers_are_reported():
    wrapper = ElementTree.Element(f"{_W}sdt")
    content = ElementTree.SubElement(wrapper, f"{_W}sdtContent")
    content.append(_p("Not indexed through wrapper"))

    index = build_docx_ooxml_index(_docx_bytes(wrapper))

    assert index["elements"] == []
    assert index["unsupported_structures"] == [
        {
            "tag": "w:sdt",
            "context": "document-body",
            "parent_path": [],
            "child_index": 0,
        }
    ]


def test_unsupported_paragraph_content_is_reported():
    paragraph = _p(
        _run_with(
            ElementTree.Element(f"{_W}drawing"),
        )
    )

    index = build_docx_ooxml_index(_docx_bytes(paragraph))

    assert index["elements"][0]["text"] == ""
    assert index["unsupported_structures"][0]["tag"] == "w:drawing"
    assert index["unsupported_structures"][0]["parent_path"] == [
        {"kind": "paragraph", "index": 0}
    ]


def test_index_is_deterministic_for_same_docx_bytes():
    docx = _docx_bytes(
        _p("First"),
        _table([[[_p("Cell")]]]),
        _p("Last"),
    )

    assert build_docx_ooxml_index(docx) == build_docx_ooxml_index(docx)


def test_invalid_zip_raises_clear_index_error():
    with pytest.raises(DOCXOOXMLIndexError, match="valid ZIP"):
        build_docx_ooxml_index(b"not a zip file")


def test_missing_document_xml_raises_clear_index_error():
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/styles.xml", b"<styles/>")

    with pytest.raises(DOCXOOXMLIndexError, match="missing word/document.xml"):
        build_docx_ooxml_index(output.getvalue())


def test_malformed_document_xml_raises_clear_index_error():
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            b"<w:document><w:body>",
        )

    with pytest.raises(DOCXOOXMLIndexError, match="malformed XML"):
        build_docx_ooxml_index(output.getvalue())
