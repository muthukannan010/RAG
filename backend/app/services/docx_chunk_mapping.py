"""Map chunk provenance ranges onto verified DOCX locator segments.

Chunk provenance offsets address the block text used by the chunker. Paragraph
blocks are the stripped Unstructured text; table blocks are the flattened
``table_html`` text produced by ingestion. Locator ranges address canonical
OOXML text. This module translates between those coordinate systems only when
their normalized text can be verified.
"""

import re
from html.parser import HTMLParser
from typing import Any

from pydantic import ValidationError

from app.models.schema import DOCXLocatorSegment


class DOCXChunkMappingError(ValueError):
    """Raised when chunk, provenance, or alignment inputs are malformed."""


def _normalize_with_ranges(text: str):
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


def _path_key(path):
    if not isinstance(path, list) or not path:
        raise DOCXChunkMappingError("OOXML element paths must be non-empty lists.")
    if any(
        not isinstance(step, dict)
        or not isinstance(step.get("kind"), str)
        or not isinstance(step.get("index"), int)
        or isinstance(step.get("index"), bool)
        or step["index"] < 0
        for step in path
    ):
        raise DOCXChunkMappingError("OOXML element path steps are invalid.")
    return tuple((step["kind"], step["index"]) for step in path)


def _index_paragraphs(structural_index):
    if not isinstance(structural_index, dict):
        raise DOCXChunkMappingError("The OOXML index must be a mapping.")

    elements = structural_index.get("elements")
    if not isinstance(elements, list):
        raise DOCXChunkMappingError("The OOXML index requires an elements list.")
    paragraphs = {}

    def add_paragraph(element):
        if not isinstance(element.get("text"), str):
            raise DOCXChunkMappingError(
                "OOXML paragraph records require string text."
            )
        key = _path_key(element.get("structural_path"))
        if key in paragraphs:
            raise DOCXChunkMappingError(
                "OOXML paragraph structural paths must be unique."
            )
        paragraphs[key] = element

    def visit_table(table):
        rows = table.get("rows")
        if not isinstance(rows, list):
            raise DOCXChunkMappingError("OOXML tables require a rows list.")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(
                row.get("cells"), list
            ):
                raise DOCXChunkMappingError(
                    "OOXML table rows require a cells list."
                )
            for cell in row["cells"]:
                if not isinstance(cell, dict) or not isinstance(
                    cell.get("elements"), list
                ):
                    raise DOCXChunkMappingError(
                        "OOXML table cells require an elements list."
                    )
                for element in cell["elements"]:
                    if not isinstance(element, dict):
                        raise DOCXChunkMappingError(
                            "OOXML table elements must be mappings."
                        )
                    if element.get("element_type") == "table":
                        visit_table(element)
                    elif element.get("element_type") == "table_cell_paragraph":
                        add_paragraph(element)
                    else:
                        raise DOCXChunkMappingError(
                            "OOXML cells may contain only paragraphs or tables."
                        )

    for element in elements:
        if not isinstance(element, dict):
            raise DOCXChunkMappingError(
                "OOXML top-level elements must be mappings."
            )
        if element.get("element_type") == "table":
            visit_table(element)
        elif element.get("element_type") == "paragraph":
            add_paragraph(element)
        else:
            raise DOCXChunkMappingError(
                "OOXML body elements must be paragraphs or tables."
            )
    return paragraphs


def _canonical_segment(locator, paragraphs, version):
    try:
        validated = DOCXLocatorSegment.model_validate(locator)
    except ValidationError:
        return None, "Alignment returned an invalid locator segment."
    if not validated.is_verified:
        return None, "Alignment locator is not verified."
    if validated.document_version_id != version:
        return None, "Alignment locator belongs to a different document version."
    if validated.element_type not in {"paragraph", "table_cell_paragraph"}:
        return None, "Alignment locator is not a paragraph or table-cell paragraph."

    paragraph = paragraphs.get(_path_key(locator["structural_path"]))
    if paragraph is None:
        return None, "Locator path is absent from the supplied OOXML index."
    if paragraph["element_type"] != validated.element_type:
        return None, "Locator path type does not match the OOXML index."

    start = validated.text_range.start
    end = validated.text_range.end
    text = paragraph["text"]
    if end > len(text):
        return None, "Alignment range exceeds canonical OOXML text."
    return text[start:end], None


def _select_normalized_positions(
    source_ranges,
    start,
    end,
):
    selected = []
    for normalized_index, (source_start, source_end) in enumerate(
        source_ranges
    ):
        if source_start < end and source_end > start:
            if source_start < start or source_end > end:
                return None, (
                    "Chunk boundary splits a whitespace run that matching "
                    "normalization collapsed."
                )
            selected.append(normalized_index)
    return selected, None


def _translate_block_range(
    block_text,
    source_range,
    locators,
    paragraphs,
    version,
):
    start, end = source_range
    if start < 0 or end <= start or end > len(block_text):
        return None, "Chunk provenance range is outside its source block."

    block_normalized, block_ranges = _normalize_with_ranges(block_text)
    canonical_normalized = []
    canonical_maps = []

    for locator_index, locator in enumerate(locators):
        canonical_text, error = _canonical_segment(
            locator,
            paragraphs,
            version,
        )
        if error:
            return None, error
        normalized, ranges = _normalize_with_ranges(canonical_text)
        if locator_index:
            canonical_normalized.append(" ")
            canonical_maps.append(None)
        canonical_normalized.append(normalized)
        canonical_maps.extend(
            [
                (
                    locator_index,
                    locator["text_range"]["start"] + source_start,
                    locator["text_range"]["start"] + source_end,
                )
                for source_start, source_end in ranges
            ]
        )

    if block_normalized != "".join(canonical_normalized):
        return None, (
            "Normalized extraction text does not match the aligned canonical "
            "OOXML segments."
        )

    selected, error = _select_normalized_positions(block_ranges, start, end)
    if error:
        return None, error

    ranges_by_locator = {}
    for normalized_index in selected:
        source_map = canonical_maps[normalized_index]
        if source_map is None:
            continue
        locator_index, source_start, source_end = source_map
        ranges_by_locator.setdefault(locator_index, []).append(
            (source_start, source_end)
        )

    mapped = []
    for locator_index, ranges in sorted(ranges_by_locator.items()):
        locator = dict(locators[locator_index])
        locator["text_range"] = {
            "start": min(source_start for source_start, _ in ranges),
            "end": max(source_end for _, source_end in ranges),
        }
        try:
            validated = DOCXLocatorSegment.model_validate(locator)
        except ValidationError:
            return None, "Translated range violates the DOCX locator contract."
        if validated.text_range.end > len(
            paragraphs[_path_key(locator["structural_path"])]["text"]
        ):
            return None, "Translated range exceeds canonical OOXML text."
        mapped.append(validated.model_dump(mode="json"))

    if not mapped:
        return None, "Chunk range contains no text mapped to an OOXML segment."
    return mapped, None


class _FlattenedTableParser(HTMLParser):
    """Mirror ingestion's table flattening while retaining cell offsets."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None
        self.row_index = -1

    def handle_starttag(self, tag, _attrs):
        del _attrs
        if tag == "tr":
            self.row_index += 1
            self.row = []
        elif tag in {"td", "th"}:
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            cell_text = re.sub(r"\s+", " ", "".join(self.cell)).strip()
            self.row.append(cell_text)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if any(self.row):
                self.rows.append((self.row_index, self.row))
            self.row = None


def _flatten_table_html(table_html):
    parser = _FlattenedTableParser()
    parser.feed(table_html)
    parts = []
    spans = []
    cursor = 0

    for row_index, row in parser.rows:
        nonempty = [
            (cell_index, text)
            for cell_index, text in enumerate(row)
            if text
        ]
        if not nonempty:
            continue
        if parts:
            parts.append("\n")
            cursor += 1
        for position, (cell_index, text) in enumerate(nonempty):
            if position:
                parts.append(" | ")
                cursor += 3
            start = cursor
            parts.append(text)
            cursor += len(text)
            spans.append(
                {
                    "row_index": row_index,
                    "cell_index": cell_index,
                    "start": start,
                    "end": cursor,
                    "text": text,
                }
            )
    return "".join(parts), spans


def _group_table_cell_locators(spans, locators, paragraphs, version):
    groups = []
    locator_index = 0

    for span in spans:
        target = _normalize_with_ranges(span["text"])[0]
        group = []
        normalized_parts = []
        while locator_index < len(locators):
            locator = locators[locator_index]
            if locator.get("element_type") != "table_cell_paragraph":
                return None, "Table alignment contains a non-cell locator."
            text, error = _canonical_segment(locator, paragraphs, version)
            if error:
                return None, error
            group.append(locator)
            normalized_parts.append(_normalize_with_ranges(text)[0])
            locator_index += 1
            joined = " ".join(normalized_parts)
            if joined == target:
                groups.append(group)
                break
            if not target.startswith(joined):
                return None, (
                    "Flattened table cell text does not match its aligned "
                    "OOXML paragraphs."
                )
        else:
            return None, "A flattened table cell has no aligned OOXML text."

    if locator_index != len(locators):
        return None, "Alignment contains locator segments outside table cells."
    return groups, None


def _translate_table_range(
    block_text,
    spans,
    source_range,
    locators,
    paragraphs,
    version,
):
    start, end = source_range
    if start < 0 or end <= start or end > len(block_text):
        return None, "Chunk provenance range is outside the flattened table."

    cell_groups, error = _group_table_cell_locators(
        spans,
        locators,
        paragraphs,
        version,
    )
    if error:
        return None, error

    mapped = []
    for span, locator_group in zip(spans, cell_groups):
        overlap_start = max(start, span["start"])
        overlap_end = min(end, span["end"])
        if overlap_start >= overlap_end:
            continue
        mapped_cell, error = _translate_block_range(
            span["text"],
            (
                overlap_start - span["start"],
                overlap_end - span["start"],
            ),
            locator_group,
            paragraphs,
            version,
        )
        if error:
            return None, error
        mapped.extend(mapped_cell)

    if not mapped:
        return None, "Chunk range contains no mapped table-cell text."
    return mapped, None


def _chunk_result(chunk, version, status, locators, diagnostics):
    return {
        "chunk_id": chunk.get("id"),
        "chunk_index": chunk.get("chunk_index"),
        "document_version_id": version,
        "original_chunk_text": chunk.get("text"),
        "mapping_status": status,
        "locator_segments": locators,
        "diagnostics": diagnostics,
    }


def map_chunks_to_docx_locators(
    chunks,
    alignment_results,
    structural_index,
    document_version_id,
) -> list[dict[str, Any]]:
    """Translate chunk provenance intervals into canonical OOXML ranges."""
    if (
        not isinstance(document_version_id, str)
        or not document_version_id.strip()
        or document_version_id != document_version_id.strip()
    ):
        raise DOCXChunkMappingError("A document version ID is required.")
    if not isinstance(structural_index, dict):
        raise DOCXChunkMappingError("The OOXML index must be a mapping.")

    paragraphs = _index_paragraphs(structural_index)

    if isinstance(alignment_results, (str, bytes)) or alignment_results is None:
        raise DOCXChunkMappingError("Alignment results must be a sequence.")
    try:
        alignments = list(alignment_results)
    except TypeError as exc:
        raise DOCXChunkMappingError(
            "Alignment results must be iterable."
        ) from exc

    alignment_by_index = {}
    for result in alignments:
        if not isinstance(result, dict):
            raise DOCXChunkMappingError("Each alignment result must be a mapping.")
        element_index = result.get("element_index")
        if (
            not isinstance(element_index, int)
            or isinstance(element_index, bool)
            or element_index < 0
        ):
            raise DOCXChunkMappingError(
                "Each alignment result requires a non-negative element index."
            )
        if element_index in alignment_by_index:
            raise DOCXChunkMappingError(
                "Alignment element indices must be unique."
            )
        alignment_by_index[element_index] = result

    if isinstance(chunks, (str, bytes)) or chunks is None:
        raise DOCXChunkMappingError("Chunks must be a sequence.")
    try:
        chunks = list(chunks)
    except TypeError as exc:
        raise DOCXChunkMappingError("Chunks must be iterable.") from exc

    outputs = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise DOCXChunkMappingError("Each chunk must be a mapping.")
        chunk_text = chunk.get("text")
        if not isinstance(chunk_text, str):
            raise DOCXChunkMappingError("Each chunk requires string text.")
        provenance = chunk.get("provenance")
        if not isinstance(provenance, list) or not provenance:
            outputs.append(
                _chunk_result(
                    chunk,
                    document_version_id,
                    "unresolved",
                    [],
                    ["Chunk has no structural provenance."],
                )
            )
            continue

        mapped_segments = []
        diagnostics = []
        failed_statuses = []
        for source in provenance:
            if not isinstance(source, dict):
                raise DOCXChunkMappingError(
                    "Each provenance item must be a mapping."
                )
            element_index = source.get("element_index")
            text_range = source.get("text_range")
            if (
                not isinstance(element_index, int)
                or isinstance(element_index, bool)
                or element_index < 0
            ):
                diagnostics.append("Provenance has no valid element index.")
                failed_statuses.append("unresolved")
                continue
            if not isinstance(text_range, dict):
                raise DOCXChunkMappingError(
                    "Provenance text_range must contain start and end."
                )
            start, end = text_range.get("start"), text_range.get("end")
            if (
                not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(end, int)
                or isinstance(end, bool)
                or start < 0
                or end <= start
            ):
                raise DOCXChunkMappingError(
                    "Provenance text_range must be a non-empty half-open range."
                )

            alignment = alignment_by_index.get(element_index)
            if alignment is None:
                diagnostics.append(
                    f"Extraction element {element_index} has no alignment result."
                )
                failed_statuses.append("unresolved")
                continue
            alignment_status = alignment.get("alignment_status")
            if alignment_status != "resolved":
                diagnostics.append(
                    f"Extraction element {element_index} alignment is "
                    f"{alignment_status!r}; no locator was selected."
                )
                failed_statuses.append(
                    "ambiguous"
                    if alignment_status == "ambiguous"
                    else "unresolved"
                )
                continue

            locators = alignment.get("locator_segments")
            if not isinstance(locators, list) or not locators:
                diagnostics.append(
                    f"Extraction element {element_index} has no resolved "
                    "locator segments."
                )
                failed_statuses.append("unresolved")
                continue
            if any(not isinstance(locator, dict) for locator in locators):
                diagnostics.append(
                    f"Extraction element {element_index} has malformed "
                    "locator segments."
                )
                failed_statuses.append("unresolved")
                continue
            if any(
                locator.get("document_version_id") != document_version_id
                for locator in locators
            ):
                diagnostics.append(
                    f"Extraction element {element_index} locator version "
                    "does not match the requested document version."
                )
                failed_statuses.append("unresolved")
                continue

            source_type = str(source.get("element_type", "")).lower()
            table_html = source.get("table_html")
            if source_type == "table" and isinstance(table_html, str):
                block_text, spans = _flatten_table_html(table_html)
                if block_text:
                    mapped, error = _translate_table_range(
                        block_text,
                        spans,
                        (start, end),
                        locators,
                        paragraphs,
                        document_version_id,
                    )
                else:
                    block_text = alignment.get("original_text", "").strip()
                    mapped, error = _translate_block_range(
                        block_text,
                        (start, end),
                        locators,
                        paragraphs,
                        document_version_id,
                    )
            else:
                block_text = alignment.get("original_text")
                if not isinstance(block_text, str):
                    diagnostics.append(
                        f"Extraction element {element_index} has no source text."
                    )
                    failed_statuses.append("unresolved")
                    continue
                block_text = block_text.strip()
                mapped, error = _translate_block_range(
                    block_text,
                    (start, end),
                    locators,
                    paragraphs,
                    document_version_id,
                )

            if error:
                diagnostics.append(
                    f"Extraction element {element_index}: {error}"
                )
                failed_statuses.append("unresolved")
            else:
                mapped_segments.extend(mapped)

        if failed_statuses:
            status = (
                "ambiguous"
                if "ambiguous" in failed_statuses
                else "unresolved"
            )
            outputs.append(
                _chunk_result(
                    chunk,
                    document_version_id,
                    status,
                    [],
                    diagnostics,
                )
            )
        elif not mapped_segments:
            outputs.append(
                _chunk_result(
                    chunk,
                    document_version_id,
                    "unresolved",
                    [],
                    ["Chunk provenance produced no locator segments."],
                )
            )
        else:
            outputs.append(
                _chunk_result(
                    chunk,
                    document_version_id,
                    "resolved",
                    mapped_segments,
                    diagnostics,
                )
            )

    return outputs
