"""Align Unstructured DOCX elements with the OOXML structural index.

Matching-only normalization collapses Unicode whitespace runs to one ASCII
space and strips the ends. Case, punctuation, and code points are preserved.
This is only for comparing extracted and indexed text. Returned ranges always
refer to the original, unnormalized OOXML paragraph text.
"""

from html.parser import HTMLParser
from itertools import product
from typing import Any

from pydantic import ValidationError

from app.models.schema import DOCXLocatorSegment, DOCXStructuralPathStep


class DOCXAlignmentError(ValueError):
    """Raised when extraction elements or an OOXML index are invalid."""


def _value(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _normalize_with_ranges(text):
    normalized = []
    ranges = []
    index = 0

    while index < len(text):
        if text[index].isspace():
            end = index + 1
            while end < len(text) and text[end].isspace():
                end += 1
            if normalized and end < len(text):
                normalized.append(" ")
                ranges.append((index, end))
            index = end
        else:
            normalized.append(text[index])
            ranges.append((index, index + 1))
            index += 1

    return "".join(normalized), ranges


def _normalize(text):
    return _normalize_with_ranges(text)[0]


def _extraction_records(elements):
    if elements is None or isinstance(elements, (str, bytes)):
        raise DOCXAlignmentError("Extraction elements must be a sequence.")
    try:
        elements = list(elements)
    except TypeError as exc:
        raise DOCXAlignmentError(
            "Extraction elements must be an iterable sequence."
        ) from exc

    records = []
    by_id = {}
    for index, element in enumerate(elements):
        category = _value(
            element,
            "category",
            _value(element, "element_type", type(element).__name__),
        )
        text = _value(element, "text", "")
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise DOCXAlignmentError(
                f"Extraction element {index} text must be a string."
            )

        metadata = _value(element, "metadata")
        element_id = _value(element, "id")
        parent_id = _value(metadata, "parent_id")
        depth = _value(metadata, "category_depth")
        try:
            depth = max(0, int(depth)) if depth is not None else None
        except (TypeError, ValueError):
            depth = None

        record = {
            "element": element,
            "element_index": index,
            "element_id": str(element_id) if element_id is not None else None,
            "parent_id": str(parent_id) if parent_id is not None else None,
            "element_type": str(category),
            "original_text": text,
            "normalized_text": _normalize(text),
            "is_heading": str(category).lower() in {"title", "header"},
            "category_depth": depth,
            "metadata": metadata,
        }
        records.append(record)
        if record["element_id"]:
            by_id[record["element_id"]] = record

    heading_stack = []
    for record in records:
        if record["is_heading"] and record["original_text"]:
            depth = record["category_depth"]
            if depth is None:
                heading_stack = [record["original_text"]]
            else:
                heading_stack = heading_stack[:depth]
                heading_stack.append(record["original_text"])

        explicit_path = _value(record["metadata"], "section_path")
        if isinstance(explicit_path, (list, tuple)) and all(
            isinstance(item, str) for item in explicit_path
        ):
            record["section_path"] = list(explicit_path)
            continue

        current_id = (
            record["element_id"]
            if record["is_heading"]
            else record["parent_id"]
        )
        ancestors = []
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            ancestor = by_id.get(current_id)
            if ancestor is None:
                break
            if ancestor["is_heading"] and ancestor["original_text"]:
                ancestors.append(ancestor["original_text"])
            current_id = ancestor["parent_id"]
        ancestors.reverse()
        record["section_path"] = ancestors or list(heading_stack)
    return records


def _flatten_index(index):
    if not isinstance(index, dict):
        raise DOCXAlignmentError("The OOXML structural index must be a mapping.")
    part_name = index.get("part_name")
    elements = index.get("elements")
    if not isinstance(part_name, str) or not part_name:
        raise DOCXAlignmentError("The structural index has no OOXML part name.")
    if not isinstance(elements, list):
        raise DOCXAlignmentError("The structural index has no elements list.")

    atoms = []
    tables = []

    def walk(record, parent_table=None, row_index=None, cell_index=None):
        if not isinstance(record, dict):
            raise DOCXAlignmentError("An OOXML index element must be a mapping.")
        kind = record.get("element_type")
        if kind in {"paragraph", "table_cell_paragraph"}:
            path = record.get("structural_path")
            text = record.get("text")
            paragraph_index = record.get("paragraph_index")
            if (
                not isinstance(text, str)
                or not isinstance(path, list)
                or not isinstance(paragraph_index, int)
                or paragraph_index < 0
            ):
                raise DOCXAlignmentError("An OOXML paragraph record is invalid.")
            try:
                steps = [
                    DOCXStructuralPathStep.model_validate(step)
                    for step in path
                ]
            except ValidationError as exc:
                raise DOCXAlignmentError(
                    "An OOXML paragraph path is invalid."
                ) from exc
            if not steps or steps[-1].kind != "paragraph":
                raise DOCXAlignmentError(
                    "An OOXML paragraph path has the wrong final step."
                )
            atoms.append(
                {
                    **record,
                    "atom_index": len(atoms),
                    "parent_table_index": parent_table,
                    "row_index": row_index,
                    "cell_index": cell_index,
                }
            )
        elif kind == "table":
            table_index = record.get("table_index")
            path = record.get("structural_path")
            rows = record.get("rows")
            if (
                not isinstance(table_index, int)
                or table_index < 0
                or not isinstance(path, list)
                or not isinstance(rows, list)
            ):
                raise DOCXAlignmentError("An OOXML table record is invalid.")
            try:
                steps = [
                    DOCXStructuralPathStep.model_validate(step)
                    for step in path
                ]
            except ValidationError as exc:
                raise DOCXAlignmentError(
                    "An OOXML table path is invalid."
                ) from exc
            if not steps or steps[-1].kind != "table":
                raise DOCXAlignmentError(
                    "An OOXML table path has the wrong final step."
                )
            tables.append(record)
            for row in rows:
                if not isinstance(row, dict) or not isinstance(
                    row.get("cells"), list
                ):
                    raise DOCXAlignmentError("An OOXML table row is invalid.")
                row_index = row.get("row_index")
                if not isinstance(row_index, int) or row_index < 0:
                    raise DOCXAlignmentError("An OOXML row index is invalid.")
                for cell in row["cells"]:
                    if not isinstance(cell, dict) or not isinstance(
                        cell.get("elements"), list
                    ):
                        raise DOCXAlignmentError("An OOXML table cell is invalid.")
                    cell_index = cell.get("cell_index")
                    if not isinstance(cell_index, int) or cell_index < 0:
                        raise DOCXAlignmentError("An OOXML cell index is invalid.")
                    for child in cell["elements"]:
                        walk(
                            child,
                            parent_table=table_index,
                            row_index=row_index,
                            cell_index=cell_index,
                        )
        else:
            raise DOCXAlignmentError(
                f"Unsupported OOXML index element type: {kind!r}."
            )

    for element in elements:
        walk(element)
    return part_name, atoms, tables


def _stream(atom_indices, atoms):
    text_parts = []
    refs = []
    source_to_stream = {}
    for atom_index in atom_indices:
        atom_text, ranges = _normalize_with_ranges(atoms[atom_index]["text"])
        if not atom_text:
            continue
        if text_parts:
            text_parts.append(" ")
            refs.append([])
        for char, (start, end) in zip(atom_text, ranges):
            stream_index = len(refs)
            text_parts.append(char)
            char_refs = [
                (atom_index, offset)
                for offset in range(start, end)
            ]
            refs.append(char_refs)
            for ref in char_refs:
                source_to_stream[ref] = stream_index
    return "".join(text_parts), refs, source_to_stream


def _find_all(text, needle, start=0):
    if not needle:
        return []
    matches = []
    position = text.find(needle, start)
    while position >= 0:
        matches.append((position, position + len(needle)))
        position = text.find(needle, position + 1)
    return matches


def _specs_for_match(refs, start, end):
    offsets = {}
    for char_refs in refs[start:end]:
        for atom_index, offset in char_refs:
            offsets.setdefault(atom_index, []).append(offset)
    return [
        {
            "atom_index": atom_index,
            "start": min(values),
            "end": max(values) + 1,
        }
        for atom_index, values in sorted(offsets.items())
    ]


def _spec_stream_range(spec, source_to_stream):
    positions = [
        source_to_stream[(spec["atom_index"], offset)]
        for offset in range(spec["start"], spec["end"])
        if (spec["atom_index"], offset) in source_to_stream
    ]
    return (min(positions), max(positions) + 1) if positions else None


def _section_contexts(atoms, records):
    headings = {}
    source_counts = {}
    for atom in atoms:
        normalized = _normalize(atom["text"])
        if normalized:
            source_counts[normalized] = source_counts.get(normalized, 0) + 1

    heading_counts = {}
    for record in records:
        if record["is_heading"] and record["normalized_text"]:
            text = record["normalized_text"]
            heading_counts[text] = heading_counts.get(text, 0) + 1
            headings[text] = record["category_depth"] or 0

    headings = {
        text: depth
        for text, depth in headings.items()
        if source_counts.get(text) == heading_counts[text]
    }

    stack = []
    contexts = []
    for atom in atoms:
        text = _normalize(atom["text"])
        if text in headings:
            depth = headings[text]
            stack = stack[:depth]
            stack.append(atom["text"])
        contexts.append(list(stack))
    return contexts


def _filter_section(candidates, section_path, contexts, is_heading=False):
    if not section_path or is_heading:
        return candidates
    expected = [_normalize(value) for value in section_path]
    scoped = [
        candidate
        for candidate in candidates
        if candidate["specs"]
        and [
            _normalize(value)
            for value in contexts[candidate["specs"][0]["atom_index"]]
        ]
        == expected
    ]
    return scoped or candidates


def _paragraph_candidates(record, source, refs, cursor, contexts):
    needle = record["normalized_text"]
    candidates = []
    for start, end in _find_all(source, needle, cursor):
        specs = _specs_for_match(refs, start, end)
        if specs:
            candidates.append({"start": start, "end": end, "specs": specs})
    return _filter_section(
        candidates,
        record["section_path"],
        contexts,
        record["is_heading"],
    )


def _cell_atoms(cell, paragraph_atoms):
    result = []

    def walk(element):
        if element["element_type"] in {
            "paragraph",
            "table_cell_paragraph",
        }:
            result.append(paragraph_atoms[element["paragraph_index"]])
        elif element["element_type"] == "table":
            for row in element["rows"]:
                for nested_cell in row["cells"]:
                    for child in nested_cell["elements"]:
                        walk(child)

    for child in cell["elements"]:
        walk(child)
    return result


def _cell_matches(
    cell,
    needle,
    paragraph_atoms,
    atoms,
    source_to_stream,
    cursor,
):
    atom_indices = _cell_atoms(cell, paragraph_atoms)
    text, refs, _ = _stream(atom_indices, atoms)
    if not needle:
        return [[]] if not text else []

    matches = []
    for start, end in _find_all(text, needle):
        specs = _specs_for_match(refs, start, end)
        ranges = [
            _spec_stream_range(spec, source_to_stream)
            for spec in specs
        ]
        if specs and all(
            value is not None and value[0] >= cursor
            for value in ranges
        ):
            matches.append(specs)
    return matches


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None
        self.depth = 0
        self.row_depth = None
        self.cell_depth = None

    def handle_starttag(self, tag, _attrs):
        if tag == "table":
            self.depth += 1
        elif tag == "tr" and self.depth <= 1:
            self.row = []
            self.row_depth = self.depth
        elif tag in {"td", "th"} and self.depth <= 1:
            self.cell = []
            self.cell_depth = self.depth
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data):
        if self.cell is not None and self.depth <= 1:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if (
            tag in {"td", "th"}
            and self.cell is not None
            and self.cell_depth == self.depth
        ):
            self.row.append("".join(self.cell))
            self.cell = None
            self.cell_depth = None
        elif (
            tag == "tr"
            and self.row is not None
            and self.row_depth == self.depth
        ):
            self.rows.append(self.row)
            self.row = None
            self.row_depth = None
        elif tag == "table":
            self.depth = max(0, self.depth - 1)


def _table_matrix(record):
    metadata = record["metadata"]
    table_html = _value(metadata, "text_as_html")
    if table_html:
        parser = _TableParser()
        parser.feed(str(table_html))
        if parser.rows:
            return [
                [_normalize(cell) for cell in row]
                for row in parser.rows
            ], True

    rows = []
    for line in record["original_text"].splitlines():
        if not line.strip():
            continue
        cells = line.split("|") if "|" in line else (
            line.split("\t") if "\t" in line else [line]
        )
        cells = [_normalize(cell) for cell in cells]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(cells)
    return rows, False


def _row_options(
    cells,
    extracted_cells,
    paragraph_atoms,
    atoms,
    source_to_stream,
    cursor,
):
    choices = []
    for start in range(len(cells) - len(extracted_cells) + 1):
        cell_options = []
        for offset, text in enumerate(extracted_cells):
            matches = _cell_matches(
                cells[start + offset],
                text,
                paragraph_atoms,
                atoms,
                source_to_stream,
                cursor,
            )
            if not matches:
                break
            cell_options.append(matches)
        else:
            choices.append(cell_options)
    return choices


def _table_candidates(
    record,
    tables,
    paragraph_atoms,
    atoms,
    source_to_stream,
    cursor,
    contexts,
):
    matrix, preserve_empty = _table_matrix(record)
    if not matrix or not any(cell for row in matrix for cell in row):
        return []

    candidates = []
    for table in tables:
        rows = table["rows"]
        placements = []
        if preserve_empty:
            for row_start in range(len(rows) - len(matrix) + 1):
                first_cells = rows[row_start]["cells"]
                for cell_start in range(len(first_cells)):
                    placement = []
                    for row_offset, extracted_row in enumerate(matrix):
                        cells = rows[row_start + row_offset]["cells"]
                        if cell_start + len(extracted_row) > len(cells):
                            break
                        for offset, text in enumerate(extracted_row):
                            matches = _cell_matches(
                                cells[cell_start + offset],
                                text,
                                paragraph_atoms,
                                atoms,
                                source_to_stream,
                                cursor,
                            )
                            if not matches:
                                break
                            placement.append(matches)
                        else:
                            continue
                        break
                    else:
                        placements.append(placement)
        else:
            nonempty_rows = [
                [
                    cell
                    for cell in row["cells"]
                    if _normalize(cell["text"])
                ]
                for row in rows
            ]
            nonempty_rows = [row for row in nonempty_rows if row]
            for row_start in range(len(nonempty_rows) - len(matrix) + 1):
                options_per_row = [
                    _row_options(
                        nonempty_rows[row_start + offset],
                        extracted_row,
                        paragraph_atoms,
                        atoms,
                        source_to_stream,
                        cursor,
                    )
                    for offset, extracted_row in enumerate(matrix)
                ]
                if all(options_per_row):
                    for row_choice in product(*options_per_row):
                        placements.append(
                            [
                                cell_options
                                for row_options in row_choice
                                for cell_options in row_options
                            ]
                        )

        for placement in placements:
            for variant in product(*placement):
                specs = [
                    spec
                    for cell_specs in variant
                    for spec in cell_specs
                ]
                if not specs:
                    continue
                ranges = [
                    _spec_stream_range(spec, source_to_stream)
                    for spec in specs
                ]
                if any(value is None for value in ranges):
                    continue
                candidates.append(
                    {
                        "start": min(value[0] for value in ranges),
                        "end": max(value[1] for value in ranges),
                        "specs": specs,
                    }
                )
    return _filter_section(candidates, record["section_path"], contexts)


def _paths_and_ranges(candidates, atoms):
    paths = []
    ranges = []
    seen = set()
    for candidate in candidates:
        for spec in candidate["specs"]:
            path = atoms[spec["atom_index"]]["structural_path"]
            key = tuple((step["kind"], step["index"]) for step in path)
            if key not in seen:
                paths.append(path)
                seen.add(key)
            ranges.append(
                {
                    "structural_path": path,
                    "text_range": {
                        "start": spec["start"],
                        "end": spec["end"],
                    },
                }
            )
    return paths, ranges


def _locator(spec, atoms, part_name, version, section_path):
    atom = atoms[spec["atom_index"]]
    payload = {
        "document_version_id": version,
        "part_name": part_name,
        "element_type": atom["element_type"],
        "structural_path": atom["structural_path"],
        "paragraph_index": atom["paragraph_index"],
        "text_range": {"start": spec["start"], "end": spec["end"]},
        "section_path": section_path,
        "mapping_status": "resolved",
    }
    if atom["element_type"] == "table_cell_paragraph":
        payload.update(
            {
                "table_index": atom["parent_table_index"],
                "row_index": atom["row_index"],
                "cell_index": atom["cell_index"],
                "cell_paragraph_index": atom["cell_paragraph_index"],
            }
        )
    try:
        return DOCXLocatorSegment.model_validate(payload).model_dump(
            mode="json"
        )
    except ValidationError as exc:
        raise DOCXAlignmentError(
            "The OOXML index produced a locator that violates the contract."
        ) from exc


def _result(record, status, reason, atoms, candidates=None, locators=None):
    paths, ranges = _paths_and_ranges(candidates or [], atoms)
    return {
        "element_index": record["element_index"],
        "element_id": record["element_id"],
        "element_type": record["element_type"],
        "original_text": record["original_text"],
        "alignment_status": status,
        "locator_segments": locators or [],
        "candidate_paths": paths,
        "candidate_text_ranges": ranges,
        "alignment_reason": reason,
    }


def _match_key(record, table):
    if not table:
        return record["normalized_text"]
    matrix, preserve_empty = _table_matrix(record)
    return tuple(tuple(row) for row in matrix), preserve_empty


def _choose(candidates, records, current, record, table):
    if len(candidates) == 1:
        return candidates[0], "A unique ordered structural match was found."

    key = _match_key(record, table)
    repeated_inputs = sum(
        _match_key(item, table) == key
        for item in records[current:]
        if (item["element_type"].lower() == "table") == table
    )
    if repeated_inputs > 1 and repeated_inputs == len(candidates):
        return (
            candidates[0],
            "Repeated extraction elements map to repeated source "
            "elements in document order.",
        )
    return None, "Multiple ordered source locations remain possible."


def align_docx_elements(
    extraction_elements,
    structural_index: dict[str, Any],
    document_version_id: str,
) -> list[dict[str, Any]]:
    """Align extraction output without changing its text or order.

    Each result includes the extraction index, category, original text,
    status, diagnostic, and either resolved locator segments or candidate
    paths. Ambiguous and unresolved results never contain selected locators.
    """
    if (
        not isinstance(document_version_id, str)
        or not document_version_id.strip()
        or document_version_id != document_version_id.strip()
    ):
        raise DOCXAlignmentError("A document version ID is required.")

    records = _extraction_records(extraction_elements)
    part_name, atoms, tables = _flatten_index(structural_index)
    source, source_refs, source_to_stream = _stream(
        range(len(atoms)),
        atoms,
    )
    paragraph_atoms = {
        atom["paragraph_index"]: atom["atom_index"]
        for atom in atoms
    }
    contexts = _section_contexts(atoms, records)

    results = []
    cursor = 0
    for record in records:
        is_table = record["element_type"].lower() == "table"
        if is_table:
            candidates = _table_candidates(
                record,
                tables,
                paragraph_atoms,
                atoms,
                source_to_stream,
                cursor,
                contexts,
            )
        else:
            candidates = _paragraph_candidates(
                record,
                source,
                source_refs,
                cursor,
                contexts,
            )

        if not candidates:
            results.append(
                _result(
                    record,
                    "unresolved",
                    "No ordered OOXML text matched this extraction element.",
                    atoms,
                )
            )
            continue

        selected, reason = _choose(
            candidates,
            records,
            record["element_index"],
            record,
            is_table,
        )
        if selected is None:
            results.append(
                _result(
                    record,
                    "ambiguous",
                    reason,
                    atoms,
                    candidates=candidates,
                )
            )
            continue

        locators = [
            _locator(
                spec,
                atoms,
                part_name,
                document_version_id,
                record["section_path"],
            )
            for spec in selected["specs"]
        ]
        if not locators:
            results.append(
                _result(
                    record,
                    "unresolved",
                    "The structural match has no non-empty text range.",
                    atoms,
                )
            )
            continue

        results.append(
            _result(
                record,
                "resolved",
                reason,
                atoms,
                locators=locators,
            )
        )
        cursor = max(cursor, selected["end"])
    return results
