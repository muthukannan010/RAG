import JSZip from "jszip";

const WORD_NAMESPACE =
  "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
const OMITTED_PARAGRAPH_CONTENT = new Set([
  "delText",
  "noBreakHyphen",
  "softHyphen",
  "sym",
  "txbxContent",
  "drawing",
  "pict",
  "object",
  "footnoteReference",
  "endnoteReference",
  "commentReference",
  "instrText",
  "delInstrText",
]);
const PARAGRAPH_SELECTOR = "p,h1,h2,h3,h4,h5,h6";

function wordChildren(element, localName) {
  return Array.from(element.children || []).filter(
    (child) =>
      child.namespaceURI === WORD_NAMESPACE &&
      child.localName === localName
  );
}

function wordValue(element, localName) {
  return (
    element.getAttributeNS(WORD_NAMESPACE, localName) ??
    element.getAttribute(`w:${localName}`) ??
    ""
  );
}

function canonicalParagraphText(paragraph) {
  const parts = [];

  function visit(parent) {
    for (const child of Array.from(parent.children || [])) {
      if (child.namespaceURI !== WORD_NAMESPACE) {
        visit(child);
        continue;
      }

      switch (child.localName) {
        case "t":
          parts.push(child.textContent || "");
          break;
        case "tab":
          parts.push("\t");
          break;
        case "br":
        case "cr":
          parts.push("\n");
          break;
        default:
          if (!OMITTED_PARAGRAPH_CONTENT.has(child.localName)) {
            visit(child);
          }
      }
    }
  }

  visit(paragraph);
  return parts.join("");
}

function headingLevel(paragraph) {
  const properties = wordChildren(paragraph, "pPr")[0];
  if (!properties) {
    return null;
  }

  const outlineLevel = wordChildren(properties, "outlineLvl")[0];
  if (outlineLevel) {
    const level = Number(wordValue(outlineLevel, "val"));
    if (Number.isInteger(level) && level >= 0 && level < 9) {
      return level + 1;
    }
  }

  const style = wordChildren(properties, "pStyle")[0];
  const styleId = style ? wordValue(style, "val") : "";
  const match = styleId.match(/^heading\s*([1-9])$/i);
  if (match) {
    return Number(match[1]);
  }
  return styleId.toLowerCase() === "title" ? 1 : null;
}

function pathWithStep(path, kind, index) {
  return [...path, { kind, index }];
}

function normalizedWhitespace(text) {
  return String(text).replace(/\s+/gu, " ").trim();
}

function xmlParseError(xmlDocument) {
  return (
    xmlDocument.getElementsByTagName("parsererror").length > 0 ||
    xmlDocument.documentElement?.localName === "parsererror"
  );
}

export async function buildDocxStructuralIndex(docxBytes) {
  if (!(docxBytes instanceof ArrayBuffer) && !ArrayBuffer.isView(docxBytes)) {
    throw new TypeError("DOCX bytes must be an ArrayBuffer or typed array.");
  }

  const archive = await JSZip.loadAsync(docxBytes);
  const documentPart = archive.file("word/document.xml");
  if (!documentPart) {
    throw new Error("The DOCX package is missing word/document.xml.");
  }

  const xml = await documentPart.async("string");
  const xmlDocument = new DOMParser().parseFromString(
    xml,
    "application/xml"
  );
  if (
    xmlParseError(xmlDocument) ||
    xmlDocument.documentElement?.localName !== "document" ||
    xmlDocument.documentElement?.namespaceURI !== WORD_NAMESPACE
  ) {
    throw new Error("The DOCX document XML is invalid.");
  }

  const body = xmlDocument.getElementsByTagNameNS(
    WORD_NAMESPACE,
    "body"
  )[0];
  if (!body) {
    throw new Error("The DOCX document has no body element.");
  }

  let paragraphIndex = 0;
  let tableIndex = 0;
  let bodyParagraphIndex = 0;
  let bodyTableIndex = 0;
  const paragraphs = [];
  const tables = [];
  const sectionStack = [];

  function addParagraph(
    element,
    {
      elementType,
      path,
      tableIndex: parentTableIndex = null,
      rowIndex = null,
      cellIndex = null,
      cellParagraphIndex = null,
    }
  ) {
    const text = canonicalParagraphText(element);
    const level = headingLevel(element);
    if (level !== null) {
      sectionStack.length = level - 1;
      sectionStack[level - 1] = text;
    }

    const record = {
      elementType,
      text,
      paragraphIndex: paragraphIndex++,
      structuralPath: path,
      sectionPath: sectionStack.filter(Boolean),
      headingLevel: level,
      tableIndex: parentTableIndex,
      rowIndex,
      cellIndex,
      cellParagraphIndex,
    };
    paragraphs.push(record);
    return record;
  }

  function addTable(table, path, siblingIndex) {
    const currentTableIndex = tableIndex++;
    const tablePath = pathWithStep(path, "table", siblingIndex);
    const record = {
      tableIndex: currentTableIndex,
      structuralPath: tablePath,
      rows: [],
    };
    tables.push(record);

    let rowIndex = 0;
    for (const row of wordChildren(table, "tr")) {
      const rowRecord = { rowIndex, cells: [] };
      const rowPath = pathWithStep(tablePath, "row", rowIndex);
      let cellIndex = 0;

      for (const cell of wordChildren(row, "tc")) {
        const cellPath = pathWithStep(rowPath, "cell", cellIndex);
        const cellRecord = {
          cellIndex,
          structuralPath: cellPath,
          elements: [],
        };
        let paragraphSiblingIndex = 0;
        let tableSiblingIndex = 0;

        for (const child of Array.from(cell.children || [])) {
          if (
            child.namespaceURI !== WORD_NAMESPACE ||
            child.localName === "tcPr"
          ) {
            continue;
          }
          if (child.localName === "p") {
            const paragraph = addParagraph(child, {
              elementType: "table_cell_paragraph",
              path: pathWithStep(
                cellPath,
                "paragraph",
                paragraphSiblingIndex
              ),
              tableIndex: currentTableIndex,
              rowIndex,
              cellIndex,
              cellParagraphIndex: paragraphSiblingIndex,
            });
            cellRecord.elements.push(paragraph);
            paragraphSiblingIndex += 1;
          } else if (child.localName === "tbl") {
            cellRecord.elements.push(
              addTable(child, cellPath, tableSiblingIndex)
            );
            tableSiblingIndex += 1;
          }
        }

        cellRecord.text = cellRecord.elements
          .map((element) => element.text)
          .join("\n");
        rowRecord.cells.push(cellRecord);
        cellIndex += 1;
      }

      record.rows.push(rowRecord);
      rowIndex += 1;
    }

    record.text = record.rows
      .map((row) => row.cells.map((cell) => cell.text).join("\t"))
      .join("\n");
    return record;
  }

  for (const child of Array.from(body.children || [])) {
    if (
      child.namespaceURI !== WORD_NAMESPACE ||
      child.localName === "sectPr"
    ) {
      continue;
    }
    if (child.localName === "p") {
      addParagraph(child, {
        elementType: "paragraph",
        path: [{ kind: "paragraph", index: bodyParagraphIndex }],
      });
      bodyParagraphIndex += 1;
    } else if (child.localName === "tbl") {
      addTable(child, [], bodyTableIndex);
      bodyTableIndex += 1;
    }
  }

  return {
    partName: "word/document.xml",
    paragraphs,
    tables,
  };
}

function pathKey(path) {
  if (!Array.isArray(path) || path.length === 0) {
    return null;
  }
  if (
    path.some(
      (step) =>
        !step ||
        typeof step.kind !== "string" ||
        !Number.isInteger(step.index) ||
        step.index < 0
    )
  ) {
    return null;
  }
  return path.map(({ kind, index }) => `${kind}:${index}`).join("/");
}

function collectTextUnits(element) {
  const units = [];
  let codePointOffset = 0;

  function visit(node) {
    if (node.nodeType === 3) {
      let utf16Offset = 0;
      for (const character of Array.from(node.data || "")) {
        const utf16Length = character.length;
        units.push({
          character,
          codePointOffset: codePointOffset++,
          node,
          startOffset: utf16Offset,
          endOffset: utf16Offset + utf16Length,
          kind: "text",
        });
        utf16Offset += utf16Length;
      }
      return;
    }

    if (node.nodeType !== 1) {
      return;
    }
    const tagName = String(node.tagName || "").toLowerCase();
    if (tagName === "script" || tagName === "style") {
      return;
    }
    if (tagName === "br") {
      units.push({
        character: "\n",
        codePointOffset: codePointOffset++,
        node,
        startOffset: 0,
        endOffset: 0,
        kind: "break",
      });
      return;
    }

    for (const child of Array.from(node.childNodes || [])) {
      visit(child);
    }
  }

  visit(element);
  return {
    text: units.map((unit) => unit.character).join(""),
    units,
  };
}

function normalizeUnits(units) {
  const normalized = [];
  const spans = [];
  let index = 0;

  while (index < units.length) {
    if (/^\s$/u.test(units[index].character)) {
      let end = index + 1;
      while (
        end < units.length &&
        /^\s$/u.test(units[end].character)
      ) {
        end += 1;
      }
      if (normalized.length > 0 && end < units.length) {
        normalized.push(" ");
        spans.push({ start: index, end });
      }
      index = end;
      continue;
    }
    normalized.push(units[index].character);
    spans.push({ start: index, end: index + 1 });
    index += 1;
  }

  return { text: normalized.join(""), spans };
}

function textInfo(element) {
  const collected = collectTextUnits(element);
  return {
    ...collected,
    normalized: normalizeUnits(collected.units),
  };
}

function headingLevelFromDom(element, sourceHeadingLevels) {
  const tagName = String(element.tagName || "").toLowerCase();
  const tagMatch = tagName.match(/^h([1-6])$/);
  if (tagMatch) {
    return Number(tagMatch[1]);
  }

  const className =
    typeof element.className === "string"
      ? element.className.toLowerCase()
      : "";
  const classMatch = className.match(/heading[-_ ]?([1-9])/);
  if (classMatch) {
    return Number(classMatch[1]);
  }

  return sourceHeadingLevels.get(
    normalizedWhitespace(element.textContent || "")
  ) ?? null;
}

function isInHeaderOrFooter(element) {
  return Boolean(
    element.closest?.(
      "header,footer,[class*='header'],[class*='footer']"
    )
  );
}

function collectRenderedParagraphs(root, index) {
  const sourceHeadingLevels = new Map();
  for (const paragraph of index.paragraphs) {
    if (paragraph.headingLevel === null || !paragraph.text) {
      continue;
    }
    const normalized = normalizedWhitespace(paragraph.text);
    const levels = sourceHeadingLevels.get(normalized) || new Set();
    levels.add(paragraph.headingLevel);
    sourceHeadingLevels.set(normalized, levels);
  }
  for (const [text, levels] of sourceHeadingLevels) {
    sourceHeadingLevels.set(text, levels.size === 1 ? [...levels][0] : null);
  }

  const documentOrder = new Map(
    Array.from(root.querySelectorAll("*")).map((element, position) => [
      element,
      position,
    ])
  );
  const renderedElements = Array.from(
    root.querySelectorAll(PARAGRAPH_SELECTOR)
  ).filter((element) => !isInHeaderOrFooter(element));
  renderedElements.sort(
    (left, right) =>
      (documentOrder.get(left) ?? 0) - (documentOrder.get(right) ?? 0)
  );

  const stack = [];
  const records = [];
  for (const element of renderedElements) {
    const info = textInfo(element);
    const level = headingLevelFromDom(element, sourceHeadingLevels);
    if (level !== null) {
      stack.length = level - 1;
      stack[level - 1] = normalizedWhitespace(info.text);
    }
    records.push({
      element,
      textInfo: info,
      normalizedText: info.normalized.text,
      order: documentOrder.get(element) ?? records.length,
      sectionPath: stack.filter(Boolean),
      sectionKnown: stack.some(Boolean),
      cell: element.closest?.("td,th") ?? null,
    });
  }

  return { records, documentOrder };
}

function matchingSection(candidate, expectedPath) {
  if (!expectedPath.length || !candidate.sectionKnown) {
    return true;
  }
  const expected = expectedPath.map(normalizedWhitespace);
  const actual = candidate.sectionPath.map(normalizedWhitespace);
  return (
    expected.length === actual.length &&
    expected.every((heading, index) => heading === actual[index])
  );
}

function locatorResult(locator, status, reason, extra = {}) {
  return {
    locatorPath: Array.isArray(locator?.structural_path)
      ? locator.structural_path.map((step) => ({ ...step }))
      : [],
    stableKey: pathKey(locator?.structural_path),
    domElement: null,
    domCell: null,
    canonicalTextMapping: null,
    textNodeRanges: [],
    mappingStatus: status,
    diagnosticReason: reason,
    ...extra,
  };
}

function mapTextRange(record, start, end) {
  const canonicalUnits = Array.from(record.text);
  if (
    !Number.isInteger(start) ||
    !Number.isInteger(end) ||
    start < 0 ||
    end <= start ||
    end > canonicalUnits.length
  ) {
    return {
      error: "Locator text range is outside canonical paragraph text.",
    };
  }

  const canonical = normalizeUnits(
    canonicalUnits.map((character, codePointOffset) => ({
      character,
      codePointOffset,
    }))
  );
  const rendered = record.domCandidate.textInfo.normalized;
  if (
    canonical.text !== rendered.text ||
    canonical.spans.length !== rendered.spans.length
  ) {
    return {
      error: "Rendered paragraph text does not match canonical OOXML text.",
    };
  }

  const selected = [];
  const mapping = [];
  for (let normalizedIndex = 0; normalizedIndex < canonical.spans.length; normalizedIndex += 1) {
    const canonicalSpan = canonical.spans[normalizedIndex];
    if (canonicalSpan.start >= end || canonicalSpan.end <= start) {
      continue;
    }
    if (canonicalSpan.start < start || canonicalSpan.end > end) {
      return {
        error: "Locator range splits a collapsed whitespace sequence.",
      };
    }

    const renderedSpan = rendered.spans[normalizedIndex];
    const units = record.domCandidate.textInfo.units.slice(
      renderedSpan.start,
      renderedSpan.end
    );
    mapping.push({
      normalizedText: canonical.text[normalizedIndex],
      canonicalRange: {
        start: canonicalSpan.start,
        end: canonicalSpan.end,
      },
      renderedCodePointRange: {
        start: renderedSpan.start,
        end: renderedSpan.end,
      },
    });
    selected.push(
      ...units.map((unit) => ({
        ...unit,
        canonicalStart: canonicalSpan.start,
        canonicalEnd: canonicalSpan.end,
      }))
    );
  }

  if (selected.length === 0) {
    return { error: "Locator range has no rendered text." };
  }

  const textNodeRanges = [];
  for (const unit of selected) {
    if (unit.kind !== "text") {
      continue;
    }
    const previous = textNodeRanges[textNodeRanges.length - 1];
    if (
      previous &&
      previous.textNode === unit.node &&
      previous.endOffset === unit.startOffset
    ) {
      previous.endOffset = unit.endOffset;
      previous.canonicalRange.end = Math.max(
        previous.canonicalRange.end,
        unit.canonicalEnd
      );
    } else {
      textNodeRanges.push({
        textNode: unit.node,
        startOffset: unit.startOffset,
        endOffset: unit.endOffset,
        canonicalRange: {
          start: unit.canonicalStart,
          end: unit.canonicalEnd,
        },
      });
    }
  }

  return {
    canonicalTextMapping: {
      canonicalText: record.text,
      normalizedText: canonical.text,
      canonicalOffsetUnit: "unicode-code-point",
      renderedOffsetUnit: "utf-16-code-unit",
      canonicalRange: { start, end },
      normalizedMapping: mapping,
    },
    textNodeRanges,
  };
}

function tableMatrixFromDom(table, domParagraphs) {
  const rows = Array.from(table.querySelectorAll("tr")).filter(
    (row) => row.closest?.("table") === table
  );
  return rows.map((row) =>
    Array.from(row.children || [])
      .filter((cell) => ["td", "th"].includes(
        String(cell.tagName || "").toLowerCase()
      ))
      .map((cell) => {
        const paragraphs = domParagraphs
          .filter((paragraph) => paragraph.cell === cell)
          .map((paragraph) => paragraph.textInfo.text);
        return normalizedWhitespace(paragraphs.join("\n"));
      })
  );
}

function sameMatrix(left, right) {
  return (
    left.length === right.length &&
    left.every(
      (row, rowIndex) =>
        row.length === right[rowIndex].length &&
        row.every(
          (cell, cellIndex) =>
            normalizedWhitespace(cell) ===
            normalizedWhitespace(right[rowIndex][cellIndex])
        )
    )
  );
}

function domTables(root, documentOrder) {
  return Array.from(root.querySelectorAll("table"))
    .filter((table) => !isInHeaderOrFooter(table))
    .map((table) => ({
      element: table,
      order: documentOrder.get(table) ?? 0,
    }))
    .sort((left, right) => left.order - right.order);
}

function cellParagraphCandidates(
  tableCandidate,
  sourceTable,
  paragraphRecord,
  renderedParagraphs,
  expectedPath
) {
  const rows = Array.from(
    tableCandidate.element.querySelectorAll("tr")
  ).filter((row) => row.closest?.("table") === tableCandidate.element);
  const row = rows[paragraphRecord.rowIndex];
  if (!row) {
    return [];
  }
  const cells = Array.from(row.children || []).filter((cell) =>
    ["td", "th"].includes(String(cell.tagName || "").toLowerCase())
  );
  const cell = cells[paragraphRecord.cellIndex];
  const sourceCell =
    sourceTable.rows[paragraphRecord.rowIndex]?.cells[
      paragraphRecord.cellIndex
    ];
  if (!cell || !sourceCell) {
    return [];
  }

  const cellCandidates = renderedParagraphs.filter(
    (candidate) =>
      candidate.cell === cell &&
      candidate.normalizedText ===
        normalizedWhitespace(paragraphRecord.text) &&
      matchingSection(candidate, expectedPath)
  );
  if (cellCandidates.length <= 1) {
    return cellCandidates.map((candidate) => ({
      ...candidate,
      domCell: cell,
      localParagraphIndex: renderedParagraphs
        .filter((entry) => entry.cell === cell)
        .indexOf(candidate),
    }));
  }

  const localParagraphs = renderedParagraphs.filter(
    (candidate) => candidate.cell === cell
  );
  const hinted = localParagraphs[paragraphRecord.cellParagraphIndex];
  if (
    hinted &&
    hinted.normalizedText === normalizedWhitespace(paragraphRecord.text)
  ) {
    return [{ ...hinted, domCell: cell }];
  }
  return cellCandidates.map((candidate) => ({
    ...candidate,
    domCell: cell,
  }));
}

function paragraphCandidates(
  paragraphRecord,
  renderedParagraphs,
  tableRecord,
  tables,
  expectedPath
) {
  if (paragraphRecord.elementType === "paragraph") {
    return renderedParagraphs
      .filter(
        (candidate) =>
          candidate.cell === null &&
          candidate.normalizedText ===
            normalizedWhitespace(paragraphRecord.text) &&
          matchingSection(candidate, expectedPath)
      )
      .map((candidate) => ({ ...candidate, domCell: null }));
  }

  const sourceTable = tables.indexByTableIndex.get(
    paragraphRecord.tableIndex
  );
  if (!sourceTable || !tableRecord || !tableRecord.domTables) {
    return [];
  }

  const sourceMatrix = sourceTable.rows.map((row) =>
    row.cells.map((cell) => cell.text)
  );
  const tableCandidates = tableRecord.domTables.filter((candidate) =>
    sameMatrix(
      sourceMatrix,
      tableMatrixFromDom(candidate.element, renderedParagraphs)
    )
  );
  const sectionMatches = tableCandidates.filter((candidate) =>
    matchingSection(
      tableRecord.sectionByTable.get(candidate.element),
      expectedPath
    )
  );
  const hasSectionEvidence = tableCandidates.some(
    (candidate) =>
      tableRecord.sectionByTable.get(candidate.element)?.sectionKnown
  );
  const candidates = hasSectionEvidence ? sectionMatches : tableCandidates;

  return candidates.flatMap((candidate) =>
    cellParagraphCandidates(
      candidate,
      sourceTable,
      paragraphRecord,
      renderedParagraphs,
      expectedPath
    ).map((paragraph) => ({
      ...paragraph,
      table: candidate.element,
      tableOrder: candidate.order,
    }))
  );
}

function solveOrderedCandidates(groups) {
  const solutions = [];
  const chosen = [];

  function visit(index, previousOrder) {
    if (solutions.length > 1) {
      return;
    }
    if (index === groups.length) {
      solutions.push([...chosen]);
      return;
    }
    const group = groups[index];
    for (const candidate of group.candidates) {
      if (candidate.order <= previousOrder) {
        continue;
      }
      chosen.push(candidate);
      visit(index + 1, candidate.order);
      chosen.pop();
      if (solutions.length > 1) {
        return;
      }
    }
  }

  visit(0, -1);
  return solutions;
}

export function mapDocxLocatorsToDom({
  renderedRoot,
  structuralIndex,
  locatorSegments,
  documentVersionId,
}) {
  if (
    !renderedRoot ||
    typeof renderedRoot.querySelectorAll !== "function" ||
    !Array.isArray(structuralIndex?.paragraphs) ||
    !Array.isArray(locatorSegments)
  ) {
    throw new TypeError("DOCX DOM mapping inputs are invalid.");
  }

  const paragraphByPath = new Map(
    structuralIndex.paragraphs.map((paragraph) => [
      pathKey(paragraph.structuralPath),
      paragraph,
    ])
  );
  const tableByIndex = new Map(
    structuralIndex.tables.map((table) => [table.tableIndex, table])
  );
  const tableContext = new Map();
  const { records: renderedParagraphs, documentOrder } =
    collectRenderedParagraphs(renderedRoot, structuralIndex);
  const renderedTableRecords = domTables(renderedRoot, documentOrder);

  for (const tableRecord of renderedTableRecords) {
    const priorParagraph = renderedParagraphs
      .filter((paragraph) => paragraph.order < tableRecord.order)
      .pop();
    tableContext.set(
      tableRecord.element,
      priorParagraph || {
        sectionPath: [],
        sectionKnown: false,
      }
    );
  }

  const results = locatorSegments.map((locator, inputIndex) => {
    if (!locator || locator.mapping_status !== "resolved") {
      return locatorResult(
        locator,
        locator?.mapping_status === "ambiguous"
          ? "ambiguous"
          : "unresolved",
        "The API locator is not resolved."
      );
    }
    if (!documentVersionId) {
      return locatorResult(
        locator,
        "unresolved",
        "The served document version could not be verified."
      );
    }
    if (locator.document_version_id !== documentVersionId) {
      return locatorResult(
        locator,
        "unresolved",
        "The locator belongs to a different document version."
      );
    }

    const key = pathKey(locator.structural_path);
    const paragraph = paragraphByPath.get(key);
    if (
      !paragraph ||
      paragraph.elementType !== locator.element_type
    ) {
      return locatorResult(
        locator,
        "unresolved",
        "The structural path does not identify a canonical paragraph."
      );
    }

    const start = locator.text_range?.start;
    const end = locator.text_range?.end;
    const canonicalLength = Array.from(paragraph.text).length;
    if (
      !Number.isInteger(start) ||
      !Number.isInteger(end) ||
      start < 0 ||
      end <= start ||
      end > canonicalLength
    ) {
      return locatorResult(
        locator,
        "unresolved",
        "Locator text range is outside canonical paragraph text."
      );
    }

    const expectedPath = Array.isArray(locator.section_path)
      ? locator.section_path
      : paragraph.sectionPath;
    const tableRecord = {
      domTables: renderedTableRecords,
      sectionByTable: tableContext,
    };
    const candidates = paragraphCandidates(
      paragraph,
      renderedParagraphs,
      tableRecord,
      { indexByTableIndex: tableByIndex },
      expectedPath
    ).filter((candidate) => {
      const domInfo = candidate.textInfo;
      return (
        domInfo.normalized.text ===
        normalizedWhitespace(paragraph.text)
      );
    });

    if (candidates.length === 0) {
      return locatorResult(
        locator,
        "unresolved",
        "No rendered paragraph matches canonical OOXML text."
      );
    }

    const selectedCandidate = candidates.length === 1
      ? candidates[0]
      : null;
    return {
      locator,
      paragraph,
      start,
      end,
      inputIndex,
      key,
      candidates,
      selectedCandidate,
      output: null,
    };
  });

  const groupsByKey = new Map();
  for (const result of results) {
    if (!result || !result.key) {
      continue;
    }
    if (!result.candidates) {
      continue;
    }
    let group = groupsByKey.get(result.key);
    if (!group) {
      group = {
        key: result.key,
        paragraph: result.paragraph,
        candidates: result.candidates,
        results: [],
      };
      groupsByKey.set(result.key, group);
    } else {
      group.candidates = group.candidates.filter((candidate) =>
        result.candidates.some(
          (candidateItem) =>
            candidateItem.element === candidate.element
        )
      );
    }
    group.results.push(result);
  }

  const orderedGroups = [...groupsByKey.values()]
    .filter((group) => group.candidates.length > 0)
    .sort(
      (left, right) =>
        left.paragraph.paragraphIndex -
        right.paragraph.paragraphIndex
    );
  const solutions = solveOrderedCandidates(orderedGroups);

  for (const group of orderedGroups) {
    let candidate = null;
    let status = "resolved";
    let reason = "Rendered paragraph text and structural context match.";
    if (solutions.length === 1) {
      candidate = solutions[0][orderedGroups.indexOf(group)];
    } else if (solutions.length > 1 || group.candidates.length > 1) {
      status = "ambiguous";
      reason = "Multiple rendered DOM elements match this locator.";
    } else {
      status = "unresolved";
      reason = "Rendered elements do not preserve locator document order.";
    }

    for (const result of group.results) {
      if (status !== "resolved" || !candidate) {
        results[result.inputIndex] = locatorResult(
          result.locator,
          status,
          reason,
          {
            candidateElementKeys: group.candidates.map(
              (item) => `rendered-paragraph-${item.order}`
            ),
          }
        );
        continue;
      }

      const rangeMapping = mapTextRange(
        {
          ...result.paragraph,
          domCandidate: candidate,
        },
        result.start,
        result.end
      );
      if (rangeMapping.error) {
        results[result.inputIndex] = locatorResult(
          result.locator,
          "unresolved",
          rangeMapping.error
        );
        continue;
      }

      results[result.inputIndex] = {
        locatorPath: result.locator.structural_path.map((step) => ({
          ...step,
        })),
        stableKey: `docx-${result.key}`,
        domElement: candidate.element,
        domCell: candidate.domCell || null,
        canonicalTextMapping: rangeMapping.canonicalTextMapping,
        textNodeRanges: rangeMapping.textNodeRanges,
        mappingStatus: "resolved",
        diagnosticReason: reason,
      };
    }
  }

  return results;
}
