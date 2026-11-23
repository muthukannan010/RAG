import assert from "node:assert/strict";
import test from "node:test";

import { normalizeSearchResponse, normalizeSource } from "./normal.js";

const resolvedSegment = {
  document_version_id: "version-1",
  element_type: "paragraph",
  structural_path: [{ kind: "paragraph", index: 2 }],
  paragraph_index: 2,
  text_range: { start: 0, end: 15 },
  mapping_status: "resolved",
};

test("normalizes resolved DOCX locators and retains citation data", () => {
  const structuralMetadata = [
    { format: "docx", element_type: "Paragraph" },
  ];
  const locatorSegments = [resolvedSegment];
  const normalized = normalizeSearchResponse({
    answer: "Answer",
    results: [
      {
        source_ref: "S1",
        chunk_id: "chunk-1",
        document_id: "document-1",
        version_id: "version-1",
        filename: "sample.docx",
        content: "Cited passage",
        structural_metadata: structuralMetadata,
        locator_mapping_status: "resolved",
        locator_segments: locatorSegments,
      },
    ],
  });
  const [source] = normalized.results;

  assert.equal(source.docxLocatorNavigable, true);
  assert.equal(source.versionId, "version-1");
  assert.equal(source.sourceRef, "S1");
  assert.strictEqual(source.structuralMetadata, structuralMetadata);
  assert.strictEqual(source.locatorSegments, locatorSegments);
});

test("does not enable navigation for ambiguous or unresolved mappings", () => {
  for (const status of ["ambiguous", "unresolved"]) {
    const source = normalizeSource({
      filename: "sample.docx",
      version_id: "version-1",
      locator_mapping_status: status,
      locator_segments: [],
    });

    assert.equal(source.docxLocatorNavigable, false);
  }
});

test("does not enable navigation when a resolved segment has another version", () => {
  const source = normalizeSource({
    filename: "sample.docx",
    version_id: "version-1",
    locator_mapping_status: "resolved",
    locator_segments: [
      { ...resolvedSegment, document_version_id: "version-2" },
    ],
  });

  assert.equal(source.docxLocatorNavigable, false);
});

test("keeps legacy PDF sources compatible without locator metadata", () => {
  const source = normalizeSource({
    filename: "legacy.pdf",
    document_id: "document-1",
    page_number: 3,
    content: "PDF passage",
  });

  assert.equal(source.isPdf, true);
  assert.equal(source.page, 3);
  assert.equal(source.locatorMappingStatus, null);
  assert.equal(source.locatorSegments, null);
  assert.equal(source.docxLocatorNavigable, false);
});

test("preserves locator mapping nested in structural metadata", () => {
  const mapping = {
    document_version_id: "version-1",
    mapping_status: "resolved",
    locator_segments: [resolvedSegment],
  };
  const structuralMetadata = {
    source: "unstructured",
    locator_mapping: mapping,
  };
  const source = normalizeSource({
    filename: "sample.docx",
    structural_metadata: structuralMetadata,
  });

  assert.equal(source.versionId, "version-1");
  assert.equal(source.locatorMappingStatus, "resolved");
  assert.strictEqual(source.locatorSegments, mapping.locator_segments);
  assert.equal(source.docxLocatorNavigable, true);
  assert.strictEqual(source.structuralMetadata, structuralMetadata);
});

test("extracts a locator mapping record from provenance metadata", () => {
  const mapping = {
    document_version_id: "version-1",
    mapping_status: "resolved",
    locator_segments: [resolvedSegment],
  };
  const structuralMetadata = [
    { format: "docx", element_type: "Paragraph" },
    {
      metadata_type: "docx_locator_mapping",
      locator_mapping: mapping,
    },
  ];
  const source = normalizeSource({
    filename: "sample.docx",
    structural_metadata: structuralMetadata,
  });

  assert.equal(source.docxLocatorNavigable, true);
  assert.equal(source.versionId, "version-1");
  assert.strictEqual(source.structuralMetadata, structuralMetadata);
});
