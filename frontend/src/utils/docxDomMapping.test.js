import assert from "node:assert/strict";
import test from "node:test";
import JSZip from "jszip";

import {
  buildDocxStructuralIndex,
  mapDocxLocatorsToDom,
} from "./docxDomMapping.js";

const WORD_NAMESPACE =
  "http://schemas.openxmlformats.org/wordprocessingml/2006/main";

function decodeXml(value) {
  return value
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

class TestXmlElement {
  constructor(name, namespaceURI, attributes) {
    this.nodeType = 1;
    this.name = name;
    this.localName = name.split(":").pop();
    this.namespaceURI = namespaceURI || null;
    this.children = [];
    this.childNodes = [];
    this.textParts = [];
    this.attributes = attributes;
  }

  appendText(value) {
    const textValue = decodeXml(value);
    this.textParts.push(textValue);
    this.childNodes.push({ nodeType: 3, textContent: textValue });
  }

  append(child) {
    this.children.push(child);
    this.childNodes.push(child);
  }

  get textContent() {
    return this.childNodes
      .map((child) =>
        child.nodeType === 3 ? child.textContent : child.textContent
      )
      .join("");
  }

  getAttribute(name) {
    return this.attributes.find((attribute) => attribute.name === name)
      ?.value ?? null;
  }

  getAttributeNS(namespaceURI, localName) {
    return this.attributes.find(
      (attribute) =>
        attribute.namespaceURI === namespaceURI &&
        attribute.localName === localName
    )?.value ?? null;
  }

  getElementsByTagNameNS(namespaceURI, localName) {
    const matches = [];
    function visit(element) {
      for (const child of element.children) {
        if (
          child.namespaceURI === namespaceURI &&
          child.localName === localName
        ) {
          matches.push(child);
        }
        visit(child);
      }
    }
    visit(this);
    return matches;
  }

  getElementsByTagName(name) {
    const matches = [];
    function visit(element) {
      for (const child of element.children) {
        if (child.name === name) {
          matches.push(child);
        }
        visit(child);
      }
    }
    visit(this);
    return matches;
  }
}

class TestDOMParser {
  parseFromString(xml) {
    const stack = [];
    let documentElement = null;
    const tokens = xml.match(/<!--[\s\S]*?-->|<[^>]+>|[^<]+/g) || [];
    for (const token of tokens) {
      if (token.startsWith("<!--") || token.startsWith("<?")) {
        continue;
      }
      if (token.startsWith("</")) {
        stack.pop();
        continue;
      }
      if (!token.startsWith("<")) {
        stack[stack.length - 1]?.appendText(token);
        continue;
      }

      const selfClosing = /\/>$/.test(token);
      const inner = token.slice(1, selfClosing ? -2 : -1).trim();
      const name = inner.match(/^[^\s/]+/)?.[0];
      if (!name) {
        continue;
      }
      const parentNamespaces = stack.length
        ? stack[stack.length - 1].namespaceMap
        : {};
      const namespaceMap = { ...parentNamespaces };
      const attributes = [];
      const rawAttributes = inner.slice(name.length);
      const attributePattern =
        /([^\s=]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g;
      for (const match of rawAttributes.matchAll(attributePattern)) {
        const attributeName = match[1];
        const value = decodeXml(match[2] ?? match[3] ?? "");
        if (attributeName === "xmlns") {
          namespaceMap[""] = value;
        } else if (attributeName.startsWith("xmlns:")) {
          namespaceMap[attributeName.slice(6)] = value;
        }
        const prefix = attributeName.includes(":")
          ? attributeName.split(":")[0]
          : "";
        attributes.push({
          name: attributeName,
          value,
          localName: attributeName.split(":").pop(),
          namespaceURI:
            attributeName === "xmlns" || prefix === "xmlns"
              ? "http://www.w3.org/2000/xmlns/"
              : namespaceMap[prefix] || null,
        });
      }
      const prefix = name.includes(":") ? name.split(":")[0] : "";
      const element = new TestXmlElement(
        name,
        namespaceMap[prefix],
        attributes
      );
      element.namespaceMap = namespaceMap;
      if (stack.length) {
        stack[stack.length - 1].append(element);
      } else {
        documentElement = element;
      }
      if (!selfClosing) {
        stack.push(element);
      }
    }

    return {
      documentElement,
      getElementsByTagName(name) {
        return documentElement?.getElementsByTagName(name) || [];
      },
      getElementsByTagNameNS(namespaceURI, localName) {
        const matches = [];
        if (
          documentElement?.namespaceURI === namespaceURI &&
          documentElement.localName === localName
        ) {
          matches.push(documentElement);
        }
        if (documentElement) {
          matches.push(
            ...documentElement.getElementsByTagNameNS(
              namespaceURI,
              localName
            )
          );
        }
        return matches;
      },
    };
  }
}

async function createDocx(xml) {
  const zip = new JSZip();
  zip.file("word/document.xml", xml);
  return zip.generateAsync({ type: "arraybuffer" });
}

function withTestDomParser(callback) {
  const previous = Object.getOwnPropertyDescriptor(
    globalThis,
    "DOMParser"
  );
  Object.defineProperty(globalThis, "DOMParser", {
    configurable: true,
    value: TestDOMParser,
  });
  return Promise.resolve()
    .then(callback)
    .finally(() => {
      if (previous) {
        Object.defineProperty(globalThis, "DOMParser", previous);
      } else {
        delete globalThis.DOMParser;
      }
    });
}

function text(value) {
  return {
    nodeType: 3,
    data: value,
    parentNode: null,
    parentElement: null,
  };
}

function element(tagName, children = [], className = "") {
  const node = {
    nodeType: 1,
    tagName: tagName.toUpperCase(),
    className,
    childNodes: [],
    children: [],
    parentNode: null,
    parentElement: null,
    get textContent() {
      return this.childNodes
        .map((child) =>
          child.nodeType === 3 ? child.data : child.textContent
        )
        .join("");
    },
    append(child) {
      child.parentNode = this;
      child.parentElement = this;
      this.childNodes.push(child);
      if (child.nodeType === 1) {
        this.children.push(child);
      }
      return this;
    },
    closest(selector) {
      const selectors = selector.split(",").map((item) => item.trim());
      let current = this;
      while (current) {
        const tag = current.tagName.toLowerCase();
        const matches = selectors.some((item) => {
          if (item === "td,th") {
            return tag === "td" || tag === "th";
          }
          if (item.startsWith("[class*=")) {
            const value = item.match(/class\*=['"]([^'"]+)/)?.[1] || "";
            return current.className.includes(value);
          }
          return item === tag;
        });
        if (matches) {
          return current;
        }
        current = current.parentElement;
      }
      return null;
    },
    querySelectorAll(selector) {
      const selectors = selector.split(",").map((item) => item.trim());
      const matches = (candidate) =>
        selectors.includes("*") ||
        selectors.includes(candidate.tagName.toLowerCase());
      const found = [];
      function visit(parent) {
        for (const child of parent.children) {
          if (matches(child)) {
            found.push(child);
          }
          visit(child);
        }
      }
      visit(this);
      return found;
    },
  };

  for (const child of children) {
    node.append(typeof child === "string" ? text(child) : child);
  }
  return node;
}

function paragraph(value, options = {}) {
  const nodes = options.textNodes ?? [value];
  return element(
    "p",
    nodes.map((node) => (typeof node === "string" ? text(node) : node)),
    options.className || ""
  );
}

function rootWith(...children) {
  return element("div", children);
}

function paragraphRecord(textValue, paragraphIndex, path, extras = {}) {
  return {
    elementType: extras.elementType || "paragraph",
    text: textValue,
    paragraphIndex,
    structuralPath: path,
    sectionPath: extras.sectionPath || [],
    headingLevel: extras.headingLevel ?? null,
    tableIndex: extras.tableIndex ?? null,
    rowIndex: extras.rowIndex ?? null,
    cellIndex: extras.cellIndex ?? null,
    cellParagraphIndex: extras.cellParagraphIndex ?? null,
  };
}

function locator(record, start, end, extras = {}) {
  return {
    document_version_id: "version-1",
    element_type: record.elementType,
    structural_path: record.structuralPath,
    paragraph_index: record.paragraphIndex,
    text_range: { start, end },
    section_path: record.sectionPath,
    mapping_status: "resolved",
    ...extras,
  };
}

function map(renderedRoot, paragraphs, locatorSegments, tables = []) {
  return mapDocxLocatorsToDom({
    renderedRoot,
    structuralIndex: { paragraphs, tables },
    locatorSegments,
    documentVersionId: "version-1",
  });
}

test("indexes OOXML text, headings, paragraphs, and table-cell paths", async () => {
  const xml = `
    <w:document xmlns:w="${WORD_NAMESPACE}">
      <w:body>
        <w:p>
          <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
          <w:r><w:t>Section A</w:t></w:r>
        </w:p>
        <w:p>
          <w:r><w:t>A</w:t><w:tab/><w:t>😀</w:t><w:br/><w:t>B</w:t></w:r>
        </w:p>
        <w:tbl><w:tr><w:tc>
          <w:p><w:r><w:t>Cell text</w:t></w:r></w:p>
        </w:tc></w:tr></w:tbl>
        <w:sectPr/>
      </w:body>
    </w:document>`;
  const bytes = await createDocx(xml);

  const index = await withTestDomParser(() =>
    buildDocxStructuralIndex(bytes)
  );

  assert.equal(index.paragraphs[0].text, "Section A");
  assert.deepEqual(index.paragraphs[0].sectionPath, ["Section A"]);
  assert.equal(index.paragraphs[1].text, "A\t😀\nB");
  assert.equal(index.paragraphs[2].text, "Cell text");
  assert.deepEqual(index.paragraphs[2].structuralPath, [
    { kind: "table", index: 0 },
    { kind: "row", index: 0 },
    { kind: "cell", index: 0 },
    { kind: "paragraph", index: 0 },
  ]);
  assert.equal(index.paragraphs[2].paragraphIndex, 2);
  assert.equal(index.tables[0].rows[0].cells[0].text, "Cell text");
});

test("rejects malformed or incomplete DOCX packages during indexing", async () => {
  const missingPart = new JSZip();
  const missingBytes = await missingPart.generateAsync({
    type: "arraybuffer",
  });
  await assert.rejects(
    buildDocxStructuralIndex(missingBytes),
    /missing word\/document.xml/
  );

  const invalidXml = await createDocx("<not-a-word-document/>");
  await withTestDomParser(() =>
    assert.rejects(
      buildDocxStructuralIndex(invalidXml),
      /document XML is invalid/
    )
  );
});

test("maps exact paragraph ranges across multiple rendered text nodes", () => {
  const record = paragraphRecord(
    "Hello world",
    0,
    [{ kind: "paragraph", index: 0 }]
  );
  const firstText = text("Hel");
  const secondText = text("lo ");
  const thirdText = text("world");
  const rendered = paragraph("", {
    textNodes: [firstText, secondText, thirdText],
  });

  const [result] = map(
    rootWith(rendered),
    [record],
    [locator(record, 3, 9)]
  );

  assert.equal(result.mappingStatus, "resolved");
  assert.strictEqual(result.domElement, rendered);
  assert.deepEqual(
    result.textNodeRanges.map(({ startOffset, endOffset }) => [
      startOffset,
      endOffset,
    ]),
    [[0, 3], [0, 3]]
  );
  assert.deepEqual(
    result.textNodeRanges.map(({ canonicalRange }) => canonicalRange),
    [{ start: 3, end: 6 }, { start: 6, end: 9 }]
  );
});

test("collapses whitespace only for validation and keeps Unicode offsets correct", () => {
  const record = paragraphRecord(
    "A😀  café",
    0,
    [{ kind: "paragraph", index: 0 }]
  );
  const renderedText = text("A😀 \tcafé");
  const rendered = element("p", [renderedText]);

  const [result] = map(
    rootWith(rendered),
    [record],
    [locator(record, 1, 2)]
  );

  assert.equal(result.mappingStatus, "resolved");
  assert.deepEqual(result.textNodeRanges, [
    {
      textNode: renderedText,
      startOffset: 1,
      endOffset: 3,
      canonicalRange: { start: 1, end: 2 },
    },
  ]);
});

test("resolves repeated paragraphs only when document order uniquely identifies them", () => {
  const first = paragraphRecord(
    "repeat",
    0,
    [{ kind: "paragraph", index: 0 }]
  );
  const second = paragraphRecord(
    "repeat",
    1,
    [{ kind: "paragraph", index: 1 }]
  );
  const firstRendered = paragraph("repeat");
  const secondRendered = paragraph("repeat");

  const results = map(
    rootWith(firstRendered, secondRendered),
    [first, second],
    [locator(first, 0, 6), locator(second, 0, 6)]
  );

  assert.deepEqual(
    results.map((result) => result.mappingStatus),
    ["resolved", "resolved"]
  );
  assert.strictEqual(results[0].domElement, firstRendered);
  assert.strictEqual(results[1].domElement, secondRendered);
});

test("marks an isolated repeated paragraph ambiguous instead of guessing", () => {
  const record = paragraphRecord(
    "repeat",
    0,
    [{ kind: "paragraph", index: 0 }]
  );
  const results = map(
    rootWith(paragraph("repeat"), paragraph("repeat")),
    [record],
    [locator(record, 0, 6)]
  );

  assert.equal(results[0].mappingStatus, "ambiguous");
  assert.equal(results[0].domElement, null);
});

test("uses heading context to distinguish repeated text in different sections", () => {
  const headingA = paragraphRecord(
    "Introduction",
    0,
    [{ kind: "paragraph", index: 0 }],
    { headingLevel: 1 }
  );
  const first = paragraphRecord(
    "same passage",
    1,
    [{ kind: "paragraph", index: 1 }],
    { sectionPath: ["Introduction"] }
  );
  const headingB = paragraphRecord(
    "Appendix",
    2,
    [{ kind: "paragraph", index: 2 }],
    { headingLevel: 1 }
  );
  const second = paragraphRecord(
    "same passage",
    3,
    [{ kind: "paragraph", index: 3 }],
    { sectionPath: ["Appendix"] }
  );
  const renderedTarget = paragraph("same passage");

  const [result] = map(
    rootWith(
      element("h1", ["Introduction"]),
      paragraph("same passage"),
      element("h1", ["Appendix"]),
      renderedTarget
    ),
    [headingA, first, headingB, second],
    [locator(second, 0, 12)]
  );

  assert.equal(result.mappingStatus, "resolved");
  assert.strictEqual(result.domElement, renderedTarget);
});

test("maps a table-cell paragraph after validating table, row, cell, and text", () => {
  const path = [
    { kind: "table", index: 0 },
    { kind: "row", index: 0 },
    { kind: "cell", index: 1 },
    { kind: "paragraph", index: 0 },
  ];
  const record = paragraphRecord("target cell", 0, path, {
    elementType: "table_cell_paragraph",
    tableIndex: 0,
    rowIndex: 0,
    cellIndex: 1,
    cellParagraphIndex: 0,
  });
  const table = {
    tableIndex: 0,
    structuralPath: [{ kind: "table", index: 0 }],
    rows: [
      {
        rowIndex: 0,
        cells: [
          { cellIndex: 0, text: "left", elements: [] },
          {
            cellIndex: 1,
            text: "target cell",
            elements: [record],
          },
        ],
      },
    ],
  };
  const cellParagraph = paragraph("target cell");
  const cell = element("td", [cellParagraph]);
  const row = element("tr", [element("td", [paragraph("left")]), cell]);
  const renderedTable = element("table", [row]);

  const [result] = map(
    rootWith(renderedTable),
    [record],
    [
      locator(record, 0, 11, {
        table_index: 0,
        row_index: 0,
        cell_index: 1,
        cell_paragraph_index: 0,
      }),
    ],
    [table]
  );

  assert.equal(result.mappingStatus, "resolved");
  assert.strictEqual(result.domElement, cellParagraph);
  assert.strictEqual(result.domCell, cell);
});

test("uses validated cell paragraph order for repeated paragraphs in a cell", () => {
  const cellPath = [
    { kind: "table", index: 0 },
    { kind: "row", index: 0 },
    { kind: "cell", index: 0 },
  ];
  const first = paragraphRecord(
    "same",
    0,
    [...cellPath, { kind: "paragraph", index: 0 }],
    {
      elementType: "table_cell_paragraph",
      tableIndex: 0,
      rowIndex: 0,
      cellIndex: 0,
      cellParagraphIndex: 0,
    }
  );
  const second = paragraphRecord(
    "same",
    1,
    [...cellPath, { kind: "paragraph", index: 1 }],
    {
      elementType: "table_cell_paragraph",
      tableIndex: 0,
      rowIndex: 0,
      cellIndex: 0,
      cellParagraphIndex: 1,
    }
  );
  const table = {
    tableIndex: 0,
    structuralPath: [{ kind: "table", index: 0 }],
    rows: [
      {
        rowIndex: 0,
        cells: [
          {
            cellIndex: 0,
            text: "same\nsame",
            elements: [first, second],
          },
        ],
      },
    ],
  };
  const firstRendered = paragraph("same");
  const secondRendered = paragraph("same");
  const renderedTable = element("table", [
    element("tr", [
      element("td", [firstRendered, secondRendered]),
    ]),
  ]);

  const results = map(
    rootWith(renderedTable),
    [first, second],
    [
      locator(first, 0, 4, {
        table_index: 0,
        row_index: 0,
        cell_index: 0,
        cell_paragraph_index: 0,
      }),
      locator(second, 0, 4, {
        table_index: 0,
        row_index: 0,
        cell_index: 0,
        cell_paragraph_index: 1,
      }),
    ],
    [table]
  );

  assert.deepEqual(
    results.map((result) => result.mappingStatus),
    ["resolved", "resolved"]
  );
  assert.strictEqual(results[0].domElement, firstRendered);
  assert.strictEqual(results[1].domElement, secondRendered);
});

test("does not map mismatched versions or invalid ranges", () => {
  const record = paragraphRecord(
    "short",
    0,
    [{ kind: "paragraph", index: 0 }]
  );
  const rendered = paragraph("short");
  const results = map(
    rootWith(rendered),
    [record],
    [
      locator(record, 0, 5, {
        document_version_id: "old-version",
      }),
      locator(record, 0, 99),
    ]
  );

  assert.deepEqual(
    results.map((result) => result.mappingStatus),
    ["unresolved", "unresolved"]
  );
  assert.match(results[0].diagnosticReason, /different document version/);
  assert.match(results[1].diagnosticReason, /outside canonical paragraph/);
});

test("unresolved and ambiguous API locators cannot be promoted to resolved", () => {
  const unresolved = {
    mapping_status: "unresolved",
    structural_path: null,
    document_version_id: "version-1",
  };
  const ambiguous = {
    mapping_status: "ambiguous",
    structural_path: null,
    document_version_id: "version-1",
  };

  const results = map(rootWith(), [], [unresolved, ambiguous]);

  assert.deepEqual(
    results.map((result) => result.mappingStatus),
    ["unresolved", "ambiguous"]
  );
});
