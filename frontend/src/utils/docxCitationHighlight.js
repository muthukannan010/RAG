const HIGHLIGHT_NAME = "docx-citation";

function isValidTextRange(range, renderedRoot) {
  return (
    range?.textNode?.nodeType === 3 &&
    renderedRoot.contains(range.textNode) &&
    Number.isInteger(range.startOffset) &&
    Number.isInteger(range.endOffset) &&
    range.startOffset >= 0 &&
    range.endOffset > range.startOffset &&
    range.endOffset <= range.textNode.data.length
  );
}

function collectTextRanges(mappings, renderedRoot) {
  return mappings
    .filter((mapping) => mapping.mappingStatus === "resolved")
    .flatMap((mapping) => mapping.textNodeRanges || [])
    .filter((range) => isValidTextRange(range, renderedRoot));
}

function mergeTextRanges(ranges) {
  const grouped = new Map();
  for (const range of ranges) {
    const nodeRanges = grouped.get(range.textNode) || [];
    nodeRanges.push({
      startOffset: range.startOffset,
      endOffset: range.endOffset,
    });
    grouped.set(range.textNode, nodeRanges);
  }

  for (const nodeRanges of grouped.values()) {
    nodeRanges.sort((left, right) => left.startOffset - right.startOffset);
    for (let index = nodeRanges.length - 1; index > 0; index -= 1) {
      const current = nodeRanges[index];
      const previous = nodeRanges[index - 1];
      if (current.startOffset <= previous.endOffset) {
        previous.endOffset = Math.max(
          previous.endOffset,
          current.endOffset
        );
        nodeRanges.splice(index, 1);
      }
    }
  }
  return grouped;
}

export function clearDocxCitationHighlights(renderedRoot) {
  globalThis.CSS?.highlights?.delete(HIGHLIGHT_NAME);
  if (!renderedRoot) {
    return;
  }

  for (const mark of renderedRoot.querySelectorAll(
    "mark[data-docx-citation]"
  )) {
    const parent = mark.parentNode;
    if (!parent) {
      continue;
    }
    const fragment = renderedRoot.ownerDocument.createDocumentFragment();
    while (mark.firstChild) {
      fragment.appendChild(mark.firstChild);
    }
    parent.replaceChild(fragment, mark);
    parent.normalize?.();
  }
}

function createDomRanges(textRanges) {
  return textRanges.map(({ textNode, startOffset, endOffset }) => {
    const range = textNode.ownerDocument.createRange();
    range.setStart(textNode, startOffset);
    range.setEnd(textNode, endOffset);
    return range;
  });
}

function applyCustomHighlight(ranges) {
  if (
    typeof globalThis.Highlight !== "function" ||
    !globalThis.CSS?.highlights
  ) {
    return false;
  }
  globalThis.CSS.highlights.set(
    HIGHLIGHT_NAME,
    new globalThis.Highlight(...ranges)
  );
  return true;
}

function applyMarkFallback(textRanges) {
  const mergedRanges = mergeTextRanges(textRanges);
  for (const [textNode, ranges] of mergedRanges) {
    for (const rangeInfo of ranges.sort(
      (left, right) => right.startOffset - left.startOffset
    )) {
      const range = textNode.ownerDocument.createRange();
      range.setStart(textNode, rangeInfo.startOffset);
      range.setEnd(textNode, rangeInfo.endOffset);
      const mark = textNode.ownerDocument.createElement("mark");
      mark.dataset.docxCitation = "true";
      mark.className = "docx-citation-mark";
      range.surroundContents(mark);
    }
  }
}

export function scrollToDocxCitationSegment(mapping) {
  mapping?.domElement?.scrollIntoView?.({
    behavior: "smooth",
    block: "center",
  });
}

export function applyDocxCitationHighlights(
  renderedRoot,
  mappings
) {
  if (!renderedRoot || !Array.isArray(mappings)) {
    throw new TypeError("DOCX citation highlight inputs are invalid.");
  }

  clearDocxCitationHighlights(renderedRoot);
  const resolvedMappings = mappings.filter(
    (mapping) =>
      mapping.mappingStatus === "resolved" &&
      mapping.domElement &&
      renderedRoot.contains(mapping.domElement)
  );
  const textRanges = collectTextRanges(resolvedMappings, renderedRoot);
  if (textRanges.length === 0) {
    return { highlighted: false, segmentCount: 0 };
  }

  const ranges = createDomRanges(textRanges);
  if (!applyCustomHighlight(ranges)) {
    applyMarkFallback(textRanges);
  }
  scrollToDocxCitationSegment(resolvedMappings[0]);
  return {
    highlighted: true,
    segmentCount: resolvedMappings.length,
  };
}
