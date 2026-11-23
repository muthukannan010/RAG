import JSZip from "jszip";

const OFFICE_RELATIONSHIP_NAMESPACE =
  "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const PRESENTATION_NAMESPACE =
  "http://schemas.openxmlformats.org/presentationml/2006/main";
const DRAWING_NAMESPACE =
  "http://schemas.openxmlformats.org/drawingml/2006/main";
const SPREADSHEET_NAMESPACE =
  "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
const MAX_PREVIEW_ROWS = 1000;
const MAX_PREVIEW_COLUMNS = 100;
const MAX_PREVIEW_SLIDES = 200;

function decodeText(bytes) {
  return new TextDecoder("utf-8").decode(bytes).replace(/^\uFEFF/, "");
}

export function parseCsv(text, {
  maxRows = MAX_PREVIEW_ROWS,
  maxColumns = MAX_PREVIEW_COLUMNS,
} = {}) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  let columnTruncated = false;

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        field += character;
      }
      continue;
    }

    if (character === '"' && field.length === 0) {
      quoted = true;
    } else if (character === ",") {
      row.push(field);
      field = "";
    } else if (character === "\n" || character === "\r") {
      row.push(field);
      field = "";
      if (row.some((cell) => cell !== "")) {
        columnTruncated =
          columnTruncated || row.length > maxColumns;
        rows.push(row.slice(0, maxColumns));
      }
      row = [];
      if (character === "\r" && text[index + 1] === "\n") {
        index += 1;
      }
      if (rows.length >= maxRows) {
        return { rows, truncated: index < text.length - 1 };
      }
    } else {
      field += character;
    }
  }

  if (quoted) {
    throw new Error("CSV contains an unterminated quoted field.");
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    if (row.some((cell) => cell !== "")) {
      columnTruncated = columnTruncated || row.length > maxColumns;
      rows.push(row.slice(0, maxColumns));
    }
  }

  return {
    rows: rows.slice(0, maxRows),
    truncated: rows.length > maxRows || columnTruncated,
  };
}

export function parseMarkdownBlocks(markdown) {
  const blocks = [];
  const lines = String(markdown).replace(/\r\n?/g, "\n").split("\n");
  let paragraphLines = [];
  let codeLines = [];
  let inCode = false;

  function flushParagraph() {
    if (paragraphLines.length) {
      blocks.push({
        type: "paragraph",
        text: paragraphLines.join(" "),
      });
      paragraphLines = [];
    }
  }

  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      if (inCode) {
        blocks.push({ type: "code", text: codeLines.join("\n") });
        codeLines = [];
      } else {
        flushParagraph();
      }
      inCode = !inCode;
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      continue;
    }

    const heading = line.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      flushParagraph();
      blocks.push({
        type: "heading",
        level: heading[1].length,
        text: heading[2],
      });
      continue;
    }
    const listItem = line.match(/^\s*(?:[-*+]|\d+[.)])\s+(.+)$/);
    if (listItem) {
      flushParagraph();
      blocks.push({
        type: /^\s*\d/.test(line) ? "ordered-item" : "list-item",
        text: listItem[1],
      });
      continue;
    }
    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) {
      flushParagraph();
      blocks.push({ type: "quote", text: quote[1] });
      continue;
    }
    paragraphLines.push(line.trim());
  }

  if (inCode) {
    blocks.push({ type: "code", text: codeLines.join("\n") });
  }
  flushParagraph();
  return blocks;
}

function parseXml(xml, partName) {
  if (typeof DOMParser !== "function") {
    throw new Error("This browser cannot parse Office document previews.");
  }
  const parsed = new DOMParser().parseFromString(xml, "application/xml");
  if (
    parsed.getElementsByTagName("parsererror").length > 0 ||
    parsed.documentElement?.localName === "parsererror"
  ) {
    throw new Error(`${partName} contains malformed XML.`);
  }
  return parsed;
}

function packagePath(sourcePart, target) {
  const parts = target.startsWith("/")
    ? []
    : sourcePart.split("/").slice(0, -1);
  for (const segment of target.replace(/^\/+/, "").split("/")) {
    if (!segment || segment === ".") {
      continue;
    }
    if (segment === "..") {
      parts.pop();
    } else {
      parts.push(segment);
    }
  }
  return parts.join("/");
}

function relationshipMap(xmlDocument, sourcePart) {
  const relationships = new Map();
  const relationshipNodes = xmlDocument.getElementsByTagName(
    "Relationship"
  );
  for (const relationship of relationshipNodes) {
    const id = relationship.getAttribute("Id");
    const target = relationship.getAttribute("Target");
    if (id && target) {
      relationships.set(id, packagePath(sourcePart, target));
    }
  }
  return relationships;
}

function textForXmlNodes(parent, namespace, localName) {
  return Array.from(parent.getElementsByTagNameNS(namespace, localName))
    .map((node) => node.textContent || "")
    .join("");
}

async function loadSlides(bytes) {
  const archive = await JSZip.loadAsync(bytes);
  const presentationPart = archive.file("ppt/presentation.xml");
  const relsPart = archive.file("ppt/_rels/presentation.xml.rels");
  if (!presentationPart || !relsPart) {
    throw new Error("The PPTX package is missing its presentation index.");
  }

  const presentation = parseXml(
    await presentationPart.async("string"),
    "ppt/presentation.xml"
  );
  const relationships = relationshipMap(
    parseXml(await relsPart.async("string"), "presentation relationships"),
    "ppt/presentation.xml"
  );
  const slideIds = Array.from(
    presentation.getElementsByTagNameNS(PRESENTATION_NAMESPACE, "sldId")
  );
  const orderedParts = slideIds
    .map((slideId) =>
      relationships.get(
        slideId.getAttributeNS(OFFICE_RELATIONSHIP_NAMESPACE, "id")
      )
    )
    .filter(Boolean);
  const slideParts = orderedParts.length
    ? orderedParts
    : Object.keys(archive.files)
        .filter((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name))
        .sort((left, right) =>
          Number(left.match(/slide(\d+)/)[1]) -
          Number(right.match(/slide(\d+)/)[1])
        );

  const slides = [];
  for (const [index, partName] of slideParts
    .slice(0, MAX_PREVIEW_SLIDES)
    .entries()) {
    const part = archive.file(partName);
    if (!part) {
      continue;
    }
    const slide = parseXml(await part.async("string"), partName);
    const paragraphs = Array.from(
      slide.getElementsByTagNameNS(DRAWING_NAMESPACE, "p")
    )
      .map((paragraph) =>
        textForXmlNodes(paragraph, DRAWING_NAMESPACE, "t")
      )
      .filter(Boolean);
    slides.push({
      number: index + 1,
      title: paragraphs[0] || `Slide ${index + 1}`,
      paragraphs,
    });
  }

  return {
    slides,
    truncated: slideParts.length > MAX_PREVIEW_SLIDES,
  };
}

function columnIndex(reference) {
  const letters = String(reference).match(/^[A-Z]+/i)?.[0];
  if (!letters) {
    return -1;
  }
  return Array.from(letters.toUpperCase()).reduce(
    (value, character) => value * 26 + character.charCodeAt(0) - 64,
    0
  ) - 1;
}

async function loadSheets(bytes) {
  const archive = await JSZip.loadAsync(bytes);
  const workbookPart = archive.file("xl/workbook.xml");
  const relsPart = archive.file("xl/_rels/workbook.xml.rels");
  if (!workbookPart || !relsPart) {
    throw new Error("The XLSX package is missing its workbook index.");
  }

  const workbook = parseXml(
    await workbookPart.async("string"),
    "xl/workbook.xml"
  );
  const relationships = relationshipMap(
    parseXml(await relsPart.async("string"), "workbook relationships"),
    "xl/workbook.xml"
  );
  const sharedStringsPart = archive.file("xl/sharedStrings.xml");
  const sharedStrings = sharedStringsPart
    ? Array.from(
        parseXml(
          await sharedStringsPart.async("string"),
          "xl/sharedStrings.xml"
        ).getElementsByTagNameNS(SPREADSHEET_NAMESPACE, "si")
      ).map((item) =>
        textForXmlNodes(item, SPREADSHEET_NAMESPACE, "t")
      )
    : [];
  const sheets = Array.from(
    workbook.getElementsByTagNameNS(SPREADSHEET_NAMESPACE, "sheet")
  );

  const parsedSheets = [];
  for (const sheet of sheets) {
    const partName = relationships.get(
      sheet.getAttributeNS(OFFICE_RELATIONSHIP_NAMESPACE, "id")
    );
    const part = partName ? archive.file(partName) : null;
    if (!part) {
      continue;
    }
    const document = parseXml(await part.async("string"), partName);
    const rows = Array.from(
      document.getElementsByTagNameNS(SPREADSHEET_NAMESPACE, "row")
    );
    const data = rows.slice(0, MAX_PREVIEW_ROWS).map((row) => {
      const values = [];
      for (const cell of Array.from(
        row.getElementsByTagNameNS(SPREADSHEET_NAMESPACE, "c")
      )) {
        const index = columnIndex(cell.getAttribute("r"));
        if (index < 0 || index >= MAX_PREVIEW_COLUMNS) {
          continue;
        }
        let value = cell.getElementsByTagNameNS(
          SPREADSHEET_NAMESPACE,
          "v"
        )[0]?.textContent || "";
        if (cell.getAttribute("t") === "s") {
          value = sharedStrings[Number(value)] ?? value;
        } else if (cell.getAttribute("t") === "inlineStr") {
          value = textForXmlNodes(
            cell,
            SPREADSHEET_NAMESPACE,
            "t"
          );
        } else if (cell.getAttribute("t") === "b") {
          value = value === "1" ? "TRUE" : "FALSE";
        }
        values[index] = value;
      }
      return values;
    });
    parsedSheets.push({
      name: sheet.getAttribute("name") || `Sheet ${parsedSheets.length + 1}`,
      rows: data,
      truncated:
        rows.length > MAX_PREVIEW_ROWS ||
        rows.some((row) =>
          Array.from(
            row.getElementsByTagNameNS(SPREADSHEET_NAMESPACE, "c")
          ).some((cell) => columnIndex(cell.getAttribute("r")) >= MAX_PREVIEW_COLUMNS)
        ),
    });
  }
  return { sheets: parsedSheets };
}

export function createSandboxedHtmlDocument(
  source,
  parser = globalThis.DOMParser
) {
  if (typeof parser !== "function") {
    throw new Error("This browser cannot safely preview HTML documents.");
  }
  const document = new parser().parseFromString(
    String(source),
    "text/html"
  );
  for (const element of document.querySelectorAll(
    "script,iframe,object,embed,form,base,link,meta"
  )) {
    element.remove();
  }
  for (const element of document.querySelectorAll("*")) {
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      if (
        name.startsWith("on") ||
        name === "srcdoc" ||
        name === "href" ||
        name === "xlink:href" ||
        name === "srcset" ||
        name === "action" ||
        name === "formaction" ||
        name === "poster"
      ) {
        element.removeAttribute(attribute.name);
      } else if (name === "src") {
        if (!/^data:image\//i.test(attribute.value)) {
          element.removeAttribute(attribute.name);
        }
      } else if (
        name === "style" &&
        /(?:url\s*\(|@import)/i.test(attribute.value)
      ) {
        element.removeAttribute(attribute.name);
      }
    }
  }

  const content = document.body?.innerHTML || "";
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; script-src 'none'; connect-src 'none'; frame-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'; navigate-to 'none'"><style>body{font:16px/1.5 system-ui,sans-serif;margin:1.5rem;overflow-wrap:anywhere}img{max-width:100%;height:auto}table{max-width:100%;border-collapse:collapse}td,th{border:1px solid #999;padding:.35rem .5rem}</style></head><body>${content}</body></html>`;
}

export async function buildDocumentPreview(bytes, format) {
  switch (format) {
    case "txt":
    case "md":
    case "html":
    case "json":
    case "xml": {
      const text = decodeText(bytes);
      if (format === "json") {
        let value;
        try {
          value = JSON.parse(text);
        } catch (error) {
          throw new Error(
            `The JSON file is invalid: ${error.message}`,
            { cause: error }
          );
        }
        return { kind: "text", text: JSON.stringify(value, null, 2) };
      }
      if (format === "html") {
        return {
          kind: "html",
          html: createSandboxedHtmlDocument(text),
        };
      }
      if (format === "xml") {
        return { kind: "text", text };
      }
      return {
        kind: format === "md" ? "markdown" : "text",
        text,
      };
    }
    case "csv":
      return {
        kind: "csv",
        ...parseCsv(decodeText(bytes)),
      };
    case "pptx":
      return {
        kind: "pptx",
        ...(await loadSlides(bytes)),
      };
    case "xlsx":
      return {
        kind: "xlsx",
        ...(await loadSheets(bytes)),
      };
    default:
      return {
        kind: "unsupported",
        message: "No local preview is available for this file format.",
      };
  }
}
