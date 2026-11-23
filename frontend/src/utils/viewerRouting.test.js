import assert from "node:assert/strict";
import test from "node:test";

import {
  getSourceFileFormat,
  getSourceViewerType,
} from "./viewerRouting.js";

test("routes PDFs to the PDF viewer", () => {
  assert.equal(
    getSourceViewerType({ filename: "reports\\annual.PDF" }),
    "pdf"
  );
  assert.equal(
    getSourceViewerType({ filename: "document.docx", isPdf: true }),
    "pdf"
  );
});

test("routes DOCX sources to the original DOCX viewer", () => {
  assert.equal(
    getSourceViewerType({ filename: "reports\\source.DOCX" }),
    "docx"
  );
  assert.equal(
    getSourceViewerType({ filename: "Document", isDocx: true }),
    "docx"
  );
});

test("routes supported original formats to local previews", () => {
  for (const filename of [
    "source.txt",
    "rows.csv",
    "notes.md",
    "page.html",
    "data.json",
    "config.xml",
    "slides.pptx",
    "table.xlsx",
  ]) {
    assert.equal(getSourceViewerType({ filename }), "preview");
  }
  assert.equal(getSourceFileFormat({ filename: "notes.markdown" }), "md");
  assert.equal(getSourceFileFormat({ filename: "page.htm" }), "html");
});

test("keeps unsupported formats in the existing passage viewer", () => {
  assert.equal(
    getSourceViewerType({ filename: "archive.zip" }),
    "passage"
  );
});