import assert from "node:assert/strict";
import test from "node:test";

import {
  applyDocxCitationHighlights,
  clearDocxCitationHighlights,
} from "./docxCitationHighlight.js";

function installHighlightApi() {
  const previousCss = Object.getOwnPropertyDescriptor(globalThis, "CSS");
  const previousHighlight = Object.getOwnPropertyDescriptor(
    globalThis,
    "Highlight"
  );
  const highlights = new Map();
  class MockHighlight {
    constructor(...ranges) {
      this.ranges = ranges;
    }
  }
  Object.defineProperty(globalThis, "CSS", {
    configurable: true,
    value: { highlights },
  });
  Object.defineProperty(globalThis, "Highlight", {
    configurable: true,
    value: MockHighlight,
  });

  return () => {
    if (previousCss) {
      Object.defineProperty(globalThis, "CSS", previousCss);
    } else {
      delete globalThis.CSS;
    }
    if (previousHighlight) {
      Object.defineProperty(
        globalThis,
        "Highlight",
        previousHighlight
      );
    } else {
      delete globalThis.Highlight;
    }
  };
}

function createRenderedRoot() {
  const ranges = [];
  const document = {
    createRange() {
      const range = {
        start: null,
        end: null,
        setStart(node, offset) {
          this.start = { node, offset };
        },
        setEnd(node, offset) {
          this.end = { node, offset };
        },
      };
      ranges.push(range);
      return range;
    },
    createDocumentFragment() {
      return { appendChild() {} };
    },
  };
  const textNode = {
    nodeType: 3,
    data: "overlap text",
    ownerDocument: document,
  };
  const element = {
    scrollCount: 0,
    scrollIntoView() {
      this.scrollCount += 1;
    },
  };
  return {
    document,
    element,
    ranges,
    textNode,
    root: {
      ownerDocument: document,
      contains(node) {
        return node === element || node === textNode;
      },
      querySelectorAll() {
        return [];
      },
    },
  };
}

test("highlights overlapping citation ranges independently and scrolls to the first", () => {
  const restore = installHighlightApi();
  try {
    const rendered = createRenderedRoot();
    const result = applyDocxCitationHighlights(rendered.root, [
      {
        mappingStatus: "resolved",
        domElement: rendered.element,
        textNodeRanges: [
          {
            textNode: rendered.textNode,
            startOffset: 0,
            endOffset: 5,
          },
          {
            textNode: rendered.textNode,
            startOffset: 3,
            endOffset: 8,
          },
        ],
      },
    ]);

    assert.deepEqual(result, {
      highlighted: true,
      segmentCount: 1,
    });
    assert.equal(rendered.ranges.length, 2);
    assert.equal(rendered.element.scrollCount, 1);
    assert.equal(globalThis.CSS.highlights.get("docx-citation").ranges.length, 2);
  } finally {
    restore();
  }
});

test("does not highlight unresolved or detached DOM ranges", () => {
  const restore = installHighlightApi();
  try {
    const rendered = createRenderedRoot();
    const result = applyDocxCitationHighlights(rendered.root, [
      {
        mappingStatus: "ambiguous",
        domElement: rendered.element,
        textNodeRanges: [],
      },
      {
        mappingStatus: "resolved",
        domElement: {},
        textNodeRanges: [
          {
            textNode: rendered.textNode,
            startOffset: 0,
            endOffset: 5,
          },
        ],
      },
    ]);

    assert.deepEqual(result, {
      highlighted: false,
      segmentCount: 0,
    });
    assert.equal(rendered.ranges.length, 0);
    assert.equal(globalThis.CSS.highlights.has("docx-citation"), false);
  } finally {
    restore();
  }
});

test("removes the previous CSS highlight when changing citations", () => {
  const restore = installHighlightApi();
  try {
    const rendered = createRenderedRoot();
    applyDocxCitationHighlights(rendered.root, [
      {
        mappingStatus: "resolved",
        domElement: rendered.element,
        textNodeRanges: [
          {
            textNode: rendered.textNode,
            startOffset: 0,
            endOffset: 2,
          },
        ],
      },
    ]);

    clearDocxCitationHighlights(rendered.root);
    assert.equal(globalThis.CSS.highlights.has("docx-citation"), false);
  } finally {
    restore();
  }
});
