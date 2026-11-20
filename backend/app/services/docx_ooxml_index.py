"""Build a structural index from the main OOXML part of a DOCX package.

Paragraph text follows the locator contract: visible ``w:t`` values are
concatenated in document order, ``w:tab`` becomes ``\\t``, and ``w:br`` or
``w:cr`` becomes ``\\n``. Text and whitespace are otherwise preserved as
decoded from XML. Text offsets are Python Unicode code-point offsets and use
half-open ranges ``[start, end)``.

Structural paths use ``{"kind": ..., "index": ...}`` steps. Each index is
zero-based among same-kind siblings in its parent: top-level paragraphs and
tables are indexed separately; table paths continue with row, cell, and
paragraph steps. Nested tables extend the containing cell path.

Convenience table text joins child paragraph/table text within a cell with
newlines, cells within a row with tabs, and rows within a table with newlines.
The nested structural records remain authoritative when those delimiters make
the aggregate ambiguous.
"""

from itertools import count
from io import BytesIO
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


DOCX_DOCUMENT_PART = "word/document.xml"
WORDPROCESSING_NAMESPACE = (
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
)
_W = f"{{{WORDPROCESSING_NAMESPACE}}}"

_W_BODY = f"{_W}body"
_W_DOCUMENT = f"{_W}document"
_W_PARAGRAPH = f"{_W}p"
_W_TABLE = f"{_W}tbl"
_W_ROW = f"{_W}tr"
_W_CELL = f"{_W}tc"
_W_TEXT = f"{_W}t"
_W_TAB = f"{_W}tab"
_W_BREAK = f"{_W}br"
_W_CARRIAGE_RETURN = f"{_W}cr"
_W_SECTION_PROPERTIES = f"{_W}sectPr"
_W_TABLE_PROPERTIES = f"{_W}tblPr"
_W_TABLE_GRID = f"{_W}tblGrid"
_W_ROW_PROPERTIES = f"{_W}trPr"
_W_CELL_PROPERTIES = f"{_W}tcPr"
_W_PARAGRAPH_PROPERTIES = f"{_W}pPr"

_IGNORED_FIELD_TEXT = {
    f"{_W}instrText",
    f"{_W}delInstrText",
}
_UNSUPPORTED_PARAGRAPH_CONTENT = {
    f"{_W}delText",
    f"{_W}noBreakHyphen",
    f"{_W}softHyphen",
    f"{_W}sym",
    f"{_W}txbxContent",
    f"{_W}drawing",
    f"{_W}pict",
    f"{_W}object",
    f"{_W}footnoteReference",
    f"{_W}endnoteReference",
    f"{_W}commentReference",
}


class DOCXOOXMLIndexError(ValueError):
    """Raised when a DOCX package cannot be indexed structurally."""


def _display_tag(tag: str) -> str:
    if tag.startswith(_W):
        return f"w:{tag[len(_W):]}"
    return tag


def _path_with_step(
    path: list[dict[str, Any]],
    kind: str,
    index: int,
) -> list[dict[str, Any]]:
    return [*path, {"kind": kind, "index": index}]


def _record_unsupported(
    unsupported: list[dict[str, Any]],
    *,
    tag: str,
    context: str,
    parent_path: list[dict[str, Any]],
    child_index: int,
) -> None:
    unsupported.append(
        {
            "tag": _display_tag(tag),
            "context": context,
            "parent_path": [dict(step) for step in parent_path],
            "child_index": child_index,
        }
    )


def _paragraph_text(
    paragraph,
    *,
    path: list[dict[str, Any]],
    unsupported: list[dict[str, Any]],
) -> str:
    text_parts = []

    def visit(node, context: str) -> None:
        for child_index, child in enumerate(node):
            if child.tag == _W_TEXT:
                text_parts.append(child.text or "")
            elif child.tag == _W_TAB:
                text_parts.append("\t")
            elif child.tag in {_W_BREAK, _W_CARRIAGE_RETURN}:
                text_parts.append("\n")
            elif child.tag in _IGNORED_FIELD_TEXT:
                continue
            elif child.tag in _UNSUPPORTED_PARAGRAPH_CONTENT:
                _record_unsupported(
                    unsupported,
                    tag=child.tag,
                    context=context,
                    parent_path=path,
                    child_index=child_index,
                )
            elif child.tag == _W_PARAGRAPH or child.tag == _W_TABLE:
                _record_unsupported(
                    unsupported,
                    tag=child.tag,
                    context=context,
                    parent_path=path,
                    child_index=child_index,
                )
            elif child.tag == _W_PARAGRAPH_PROPERTIES:
                continue
            else:
                visit(child, context)

    visit(paragraph, "paragraph-content")
    return "".join(text_parts)


def _index_paragraph(
    paragraph,
    *,
    element_type: str,
    paragraph_index: int,
    cell_paragraph_index: int | None,
    path: list[dict[str, Any]],
    unsupported: list[dict[str, Any]],
) -> dict[str, Any]:
    text = _paragraph_text(
        paragraph,
        path=path,
        unsupported=unsupported,
    )
    record = {
        "element_type": element_type,
        "text": text,
        "text_length": len(text),
        "paragraph_index": paragraph_index,
        "structural_path": path,
    }
    if cell_paragraph_index is not None:
        record["cell_paragraph_index"] = cell_paragraph_index
    return record


def _index_table(
    table,
    *,
    path: list[dict[str, Any]],
    table_sibling_index: int,
    paragraph_indices,
    table_indices,
    unsupported: list[dict[str, Any]],
) -> dict[str, Any]:
    table_index = next(table_indices)
    table_path = _path_with_step(path, "table", table_sibling_index)
    table_record = {
        "element_type": "table",
        "table_index": table_index,
        "structural_path": table_path,
        "rows": [],
    }

    row_index = 0
    for child_index, child in enumerate(table):
        if child.tag in {_W_TABLE_PROPERTIES, _W_TABLE_GRID}:
            continue
        if child.tag != _W_ROW:
            _record_unsupported(
                unsupported,
                tag=child.tag,
                context="table",
                parent_path=table_path,
                child_index=child_index,
            )
            continue

        row_path = _path_with_step(table_path, "row", row_index)
        row_record = {
            "row_index": row_index,
            "cells": [],
        }
        _index_row(
            child,
            row_record=row_record,
            row_path=row_path,
            paragraph_indices=paragraph_indices,
            table_indices=table_indices,
            unsupported=unsupported,
        )
        table_record["rows"].append(row_record)
        row_index += 1

    table_record["text"] = "\n".join(
        "\t".join(cell["text"] for cell in row["cells"])
        for row in table_record["rows"]
    )
    table_record["text_length"] = len(table_record["text"])
    return table_record


def _index_row(
    row,
    *,
    row_record: dict[str, Any],
    row_path: list[dict[str, Any]],
    paragraph_indices,
    table_indices,
    unsupported: list[dict[str, Any]],
) -> None:
    cell_index = 0
    for child_index, child in enumerate(row):
        if child.tag == _W_ROW_PROPERTIES:
            continue
        if child.tag != _W_CELL:
            _record_unsupported(
                unsupported,
                tag=child.tag,
                context="table-row",
                parent_path=row_path[:-1],
                child_index=child_index,
            )
            continue

        cell_path = _path_with_step(row_path, "cell", cell_index)
        cell_record = _index_cell(
            child,
            cell_index=cell_index,
            cell_path=cell_path,
            paragraph_indices=paragraph_indices,
            table_indices=table_indices,
            unsupported=unsupported,
        )
        row_record["cells"].append(cell_record)
        cell_index += 1


def _index_cell(
    cell,
    *,
    cell_index: int,
    cell_path: list[dict[str, Any]],
    paragraph_indices,
    table_indices,
    unsupported: list[dict[str, Any]],
) -> dict[str, Any]:
    cell_record = {
        "cell_index": cell_index,
        "structural_path": cell_path,
        "elements": [],
    }

    paragraph_sibling_index = 0
    table_sibling_index = 0
    for child_index, child in enumerate(cell):
        if child.tag == _W_CELL_PROPERTIES:
            continue
        if child.tag == _W_PARAGRAPH:
            paragraph_path = _path_with_step(
                cell_path,
                "paragraph",
                paragraph_sibling_index,
            )
            paragraph_record = _index_paragraph(
                child,
                element_type="table_cell_paragraph",
                paragraph_index=next(paragraph_indices),
                cell_paragraph_index=paragraph_sibling_index,
                path=paragraph_path,
                unsupported=unsupported,
            )
            cell_record["elements"].append(paragraph_record)
            paragraph_sibling_index += 1
        elif child.tag == _W_TABLE:
            table_record = _index_table(
                child,
                path=cell_path,
                table_sibling_index=table_sibling_index,
                paragraph_indices=paragraph_indices,
                table_indices=table_indices,
                unsupported=unsupported,
            )
            cell_record["elements"].append(table_record)
            table_sibling_index += 1
        else:
            _record_unsupported(
                unsupported,
                tag=child.tag,
                context="table-cell",
                parent_path=cell_path,
                child_index=child_index,
            )

    cell_record["text"] = "\n".join(
        element["text"]
        for element in cell_record["elements"]
    )
    cell_record["text_length"] = len(cell_record["text"])
    return cell_record


def _index_body(body) -> dict[str, Any]:
    elements = []
    unsupported = []
    paragraph_indices = count()
    table_indices = count()
    paragraph_sibling_index = 0
    table_sibling_index = 0

    for child_index, child in enumerate(body):
        if child.tag == _W_SECTION_PROPERTIES:
            continue
        if child.tag == _W_PARAGRAPH:
            path = [{"kind": "paragraph", "index": paragraph_sibling_index}]
            elements.append(
                _index_paragraph(
                    child,
                    element_type="paragraph",
                    paragraph_index=next(paragraph_indices),
                    cell_paragraph_index=None,
                    path=path,
                    unsupported=unsupported,
                )
            )
            paragraph_sibling_index += 1
        elif child.tag == _W_TABLE:
            elements.append(
                _index_table(
                    child,
                    path=[],
                    table_sibling_index=table_sibling_index,
                    paragraph_indices=paragraph_indices,
                    table_indices=table_indices,
                    unsupported=unsupported,
                )
            )
            table_sibling_index += 1
        else:
            _record_unsupported(
                unsupported,
                tag=child.tag,
                context="document-body",
                parent_path=[],
                child_index=child_index,
            )

    return {
        "part_name": DOCX_DOCUMENT_PART,
        "elements": elements,
        "unsupported_structures": unsupported,
    }


def build_docx_ooxml_index(docx_bytes: bytes) -> dict[str, Any]:
    """Return ordered paragraph/table records from ``word/document.xml``.

    The returned top-level ``elements`` preserve body order. Tables contain
    rows and physical cells; each cell's ordered ``elements`` include its
    paragraphs and any nested tables. Unknown body/table/cell structures and
    unsupported paragraph content are listed rather than silently discarded.
    """
    try:
        with ZipFile(BytesIO(docx_bytes)) as archive:
            try:
                document_xml = archive.read(DOCX_DOCUMENT_PART)
            except KeyError as exc:
                raise DOCXOOXMLIndexError(
                    f"The DOCX package is missing {DOCX_DOCUMENT_PART}."
                ) from exc
    except BadZipFile as exc:
        raise DOCXOOXMLIndexError("The DOCX input is not a valid ZIP package.") from exc

    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        raise DOCXOOXMLIndexError(
            f"{DOCX_DOCUMENT_PART} contains malformed XML."
        ) from exc

    if root.tag != _W_DOCUMENT:
        raise DOCXOOXMLIndexError(
            f"{DOCX_DOCUMENT_PART} does not contain a Word document root."
        )

    body = root.find(_W_BODY)
    if body is None:
        raise DOCXOOXMLIndexError(
            f"{DOCX_DOCUMENT_PART} does not contain a document body."
        )

    return _index_body(body)
