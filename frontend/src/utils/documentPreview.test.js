import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDocumentPreview,
  createSandboxedHtmlDocument,
  parseCsv,
  parseMarkdownBlocks,
} from "./documentPreview.js";

test("parses quoted CSV fields, escaped quotes, and embedded newlines", () => {
  assert.deepEqual(
    parseCsv(
      '"Name","Notes"\r\n"Ada","says ""hello"",\nthen leaves"\r\n'
    ),
    {
      rows: [
        ["Name", "Notes"],
        ["Ada", 'says "hello",\nthen leaves'],
      ],
      truncated: false,
    }
  );
});

test("reports malformed CSV and visible preview limits", () => {
  assert.throws(() => parseCsv('"unterminated'), /unterminated/);
  assert.deepEqual(
    parseCsv("a,b,c\n1,2,3\n4,5,6", { maxRows: 1, maxColumns: 2 }),
    {
      rows: [["a", "b"]],
      truncated: true,
    }
  );
});

test("parses Markdown blocks without interpreting raw HTML", () => {
  assert.deepEqual(
    parseMarkdownBlocks(
      "# Heading\n\nA <script> stays text.\n- one\n- two\n```js\nalert(1)\n```"
    ),
    [
      { type: "heading", level: 1, text: "Heading" },
      {
        type: "paragraph",
        text: "A <script> stays text.",
      },
      { type: "list-item", text: "one" },
      { type: "list-item", text: "two" },
      { type: "code", text: "alert(1)" },
    ]
  );
});

test("formats valid JSON as text and reports malformed JSON", async () => {
  const valid = await buildDocumentPreview(
    new TextEncoder().encode('{"ok":true}'),
    "json"
  );
  assert.deepEqual(valid, {
    kind: "text",
    text: '{\n  "ok": true\n}',
  });

  await assert.rejects(
    buildDocumentPreview(new TextEncoder().encode("{"), "json"),
    /JSON file is invalid/
  );
});

test("HTML preview removes active content and applies a restrictive policy", () => {
  class MockElement {
    constructor(name, content = "", attributes = []) {
      this.name = name;
      this.content = content;
      this.attributes = attributes.map((attribute) => ({ ...attribute }));
      this.removed = false;
    }

    remove() {
      this.removed = true;
    }

    removeAttribute(name) {
      this.attributes = this.attributes.filter(
        (attribute) => attribute.name !== name
      );
    }

    get outerHTML() {
      const attributes = this.attributes
        .map(({ name, value }) => ` ${name}="${value}"`)
        .join("");
      return `<${this.name}${attributes}>${this.content}</${this.name}>`;
    }
  }

  const elements = [
    new MockElement("script", "alert(1)"),
    new MockElement("p", "safe", [
      { name: "onclick", value: "alert(1)" },
    ]),
    new MockElement("a", "link", [
      { name: "href", value: "https://example.invalid" },
    ]),
  ];
  class MockParser {
    parseFromString() {
      return {
        body: {
          get innerHTML() {
            return elements
              .filter((element) => !element.removed)
              .map((element) => element.outerHTML)
              .join("");
          },
        },
        querySelectorAll(selector) {
          if (selector === "*") {
            return elements.filter((element) => !element.removed);
          }
          const names = selector.split(",");
          return elements.filter(
            (element) =>
              !element.removed && names.includes(element.name)
          );
        },
      };
    }
  }

  const html = createSandboxedHtmlDocument(
    "<script>alert(1)</script>",
    MockParser
  );

  assert.match(html, /sandbox|Content-Security-Policy/);
  assert.match(html, /default-src 'none'/);
  assert.match(html, /<p>safe<\/p>/);
  assert.doesNotMatch(html, /<script>|onclick=|href=/i);
});
