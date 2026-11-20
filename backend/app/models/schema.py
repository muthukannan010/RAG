from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class DOCXTextRange(BaseModel):
    """Zero-based Unicode code-point offsets using the half-open form [start, end)."""

    start: int = Field(ge=0, strict=True)
    end: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def validate_nonempty_range(self):
        if self.end <= self.start:
            raise ValueError("A DOCX text range must have end greater than start.")

        return self


class DOCXStructuralPathStep(BaseModel):
    """An element's zero-based ordinal among same-kind siblings in its parent."""

    kind: Literal["paragraph", "table", "row", "cell"]
    index: int = Field(ge=0, strict=True)


def _valid_docx_path(
    element_type: Literal["paragraph", "table", "table_cell_paragraph"],
    path: list[DOCXStructuralPathStep],
) -> bool:
    kinds = [step.kind for step in path]

    if element_type == "paragraph":
        return kinds == ["paragraph"]

    if not kinds or kinds[0] != "table":
        return False

    index = 0
    while index < len(kinds):
        if kinds[index] != "table":
            return False

        index += 1
        if index == len(kinds):
            return element_type == "table"

        if index + 1 >= len(kinds):
            return False
        if kinds[index:index + 2] != ["row", "cell"]:
            return False

        index += 2
        if index == len(kinds):
            return False
        if kinds[index] == "table":
            continue
        if kinds[index] == "paragraph":
            return (
                element_type == "table_cell_paragraph"
                and index == len(kinds) - 1
            )
        return False

    return False


class DOCXLocatorSegment(BaseModel):
    """A source segment addressable in one immutable DOCX version.

    Canonical paragraph text concatenates visible ``w:t`` characters in
    document order, maps ``w:tab`` to a tab and ``w:br``/``w:cr`` to a
    newline, and otherwise preserves decoded characters and whitespace.
    Formatting markup is ignored; text is not trimmed, whitespace-collapsed,
    or Unicode-normalized. A table's canonical text joins cell paragraphs
    with newlines, cells with tabs, and rows with newlines.

    ``text_range`` indexes that canonical text in Python Unicode code points,
    zero-based, with an exclusive end. It is not a byte, UTF-16, DOM, or
    chunk-text offset.
    """

    document_version_id: str = Field(
        min_length=1,
        description="Identity of the immutable uploaded document version.",
    )
    part_name: str = "word/document.xml"
    element_type: Literal[
        "paragraph",
        "table",
        "table_cell_paragraph",
    ]
    structural_path: list[DOCXStructuralPathStep] | None = None
    paragraph_index: int | None = Field(
        default=None,
        ge=0,
        strict=True,
        description=(
            "Zero-based w:p ordinal in document order, including cell "
            "paragraphs."
        ),
    )
    table_index: int | None = Field(
        default=None,
        ge=0,
        strict=True,
        description="Zero-based w:tbl ordinal in document order.",
    )
    row_index: int | None = Field(
        default=None,
        ge=0,
        strict=True,
        description="Physical w:tr index within the identified table.",
    )
    cell_index: int | None = Field(
        default=None,
        ge=0,
        strict=True,
        description="Physical w:tc index within the identified row.",
    )
    cell_paragraph_index: int | None = Field(
        default=None,
        ge=0,
        strict=True,
        description="w:p index within the identified table cell.",
    )
    text_range: DOCXTextRange
    section_path: list[str] = Field(default_factory=list)
    mapping_status: Literal["resolved", "unresolved", "ambiguous"]
    candidate_paths: list[list[DOCXStructuralPathStep]] = Field(
        default_factory=list
    )

    @field_validator("document_version_id")
    @classmethod
    def validate_document_version_id(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError(
                "A DOCX locator requires a non-empty document version ID."
            )

        return value

    @field_validator("part_name")
    @classmethod
    def validate_part_name(cls, value: str) -> str:
        parts = value.split("/")
        if (
            not value
            or value.startswith("/")
            or "\\" in value
            or not value.endswith(".xml")
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError(
                "The OOXML part name must be a relative package XML path."
            )

        return value

    @model_validator(mode="after")
    def validate_locator_mapping(self):
        location_fields = (
            self.paragraph_index,
            self.table_index,
            self.row_index,
            self.cell_index,
            self.cell_paragraph_index,
        )

        if self.mapping_status == "resolved":
            if not self.structural_path:
                raise ValueError(
                    "A resolved DOCX locator requires a structural path."
                )
            if self.candidate_paths:
                raise ValueError(
                    "A resolved DOCX locator cannot have candidate paths."
                )
            if not _valid_docx_path(
                self.element_type,
                self.structural_path,
            ):
                raise ValueError(
                    "The structural path does not match the DOCX element type."
                )

            if self.element_type == "paragraph":
                if self.paragraph_index is None or any(
                    value is not None for value in location_fields[1:]
                ):
                    raise ValueError(
                        "A paragraph locator requires only paragraph_index."
                    )
            elif self.element_type == "table":
                if self.table_index is None or any(
                    value is not None
                    for value in (
                        self.paragraph_index,
                        self.row_index,
                        self.cell_index,
                        self.cell_paragraph_index,
                    )
                ):
                    raise ValueError(
                        "A table locator requires only table_index."
                    )
            else:
                if any(value is None for value in location_fields):
                    raise ValueError(
                        "A table-cell paragraph locator requires paragraph, "
                        "table, row, cell, and cell-paragraph indices."
                    )

                path_indices = {
                    step.kind: step.index
                    for step in self.structural_path
                    if step.kind in {"row", "cell", "paragraph"}
                }
                if (
                    path_indices.get("row") != self.row_index
                    or path_indices.get("cell") != self.cell_index
                    or path_indices.get("paragraph")
                    != self.cell_paragraph_index
                ):
                    raise ValueError(
                        "Table-cell coordinates must match the structural path."
                    )
        else:
            if self.structural_path is not None or any(
                value is not None for value in location_fields
            ):
                raise ValueError(
                    "Unresolved or ambiguous locators cannot expose a "
                    "selected structural path or coordinates."
                )
            if self.mapping_status == "unresolved":
                if self.candidate_paths:
                    raise ValueError(
                        "An unresolved locator cannot have candidate paths."
                    )
            else:
                if len(self.candidate_paths) < 2:
                    raise ValueError(
                        "An ambiguous locator requires at least two candidates."
                    )
                for candidate in self.candidate_paths:
                    if not candidate or not _valid_docx_path(
                        self.element_type,
                        candidate,
                    ):
                        raise ValueError(
                            "Each candidate path must match the DOCX element type."
                        )
                candidate_keys = [
                    tuple((step.kind, step.index) for step in candidate)
                    for candidate in self.candidate_paths
                ]
                if len(set(candidate_keys)) != len(candidate_keys):
                    raise ValueError(
                        "Ambiguous locator candidate paths must be distinct."
                    )

        return self

    @property
    def is_verified(self) -> bool:
        return (
            self.mapping_status == "resolved"
            and self.structural_path is not None
        )


class DOCXChunkLocator(BaseModel):
    """Locator segments contributing to a single retrieved chunk."""

    format: Literal["docx"] = "docx"
    locator_segments: list[DOCXLocatorSegment] = Field(min_length=1)


class DocumentSummary(BaseModel):
    id: str
    filename: str
    size_bytes: int
    page_count: int
    chunk_count: int
    status: str
    created_at: str
    updated_at: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]


class DocumentMutationResponse(BaseModel):
    message: str
    document: DocumentSummary | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("The query cannot be empty.")

        return value


class SearchResult(BaseModel):
    source_ref: str
    chunk_id: str
    document_id: str
    version_id: str | None = None
    filename: str
    page_number: int
    content: str
    structural_metadata: Any | None = None
    locator_mapping_status: Literal[
        "resolved",
        "ambiguous",
        "unresolved",
    ] | None = None
    locator_segments: list[DOCXLocatorSegment] | None = None
    semantic_score: float | None = None
    relevance_score: float | None = None
    bbox: list[list[float]]
    keyword_rank: int | None = None
    semantic_rank: int | None = None
    keyword_score: float | None = None
    hybrid_score: float | None = None
    quoted_text: str | None = None


class SearchResponse(BaseModel):
    query: str
    answer: str | None = None
    citations: list[str] = Field(default_factory=list)
    not_found: bool = False
    retrieval_mode: str = "hybrid"
    results: list[SearchResult]


class PDFPagePreviewRequest(BaseModel):
    quoted_text: str | None = Field(default=None, max_length=12000)