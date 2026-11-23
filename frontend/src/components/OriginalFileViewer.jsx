import { useEffect, useState } from "react";

import {
  buildDocumentPreview,
  parseMarkdownBlocks,
} from "../utils/documentPreview";
import { fetchOriginalDocument } from "../utils/originalDocument";

const FORMAT_LABELS = {
  csv: "CSV",
  html: "HTML",
  json: "JSON",
  md: "Markdown",
  pptx: "PowerPoint",
  txt: "Text",
  xlsx: "Excel",
  xml: "XML",
};

function MarkdownPreview({ text }) {
  const blocks = parseMarkdownBlocks(text);
  const rendered = [];

  for (let index = 0; index < blocks.length; index += 1) {
    const block = blocks[index];
    if (block.type === "list-item" || block.type === "ordered-item") {
      const ordered = block.type === "ordered-item";
      const items = [];
      while (
        index < blocks.length &&
        blocks[index].type ===
          (ordered ? "ordered-item" : "list-item")
      ) {
        items.push(blocks[index].text);
        index += 1;
      }
      index -= 1;
      const List = ordered ? "ol" : "ul";
      rendered.push(
        <List key={`list-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={`${index}-${itemIndex}`}>{item}</li>
          ))}
        </List>
      );
      continue;
    }

    if (block.type === "heading") {
      const Heading = `h${block.level}`;
      rendered.push(
        <Heading key={`heading-${index}`}>{block.text}</Heading>
      );
    } else if (block.type === "quote") {
      rendered.push(<blockquote key={`quote-${index}`}>{block.text}</blockquote>);
    } else if (block.type === "code") {
      rendered.push(
        <pre key={`code-${index}`}>
          <code>{block.text}</code>
        </pre>
      );
    } else {
      rendered.push(<p key={`paragraph-${index}`}>{block.text}</p>);
    }
  }

  return <article className="markdown-preview">{rendered}</article>;
}

function PreviewTable({ rows, label }) {
  if (!rows.length) {
    return <p className="original-preview-empty">No rows to display.</p>;
  }

  const [firstRow, ...body] = rows;
  const columnCount = Math.max(...rows.map((row) => row.length));
  const header = Array.from(
    { length: columnCount },
    (_, index) => firstRow[index] ?? ""
  );
  return (
    <div className="original-preview-table-scroll">
      <table className="original-preview-table" aria-label={label}>
        <thead>
          <tr>
            {header.map((cell, index) => (
              <th key={`head-${index}`}>{cell}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`}>
              {header.map((_, columnIndex) => (
                <td key={`cell-${rowIndex}-${columnIndex}`}>
                  {row[columnIndex] ?? ""}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DocumentPreviewContent({ preview }) {
  if (preview.kind === "html") {
    return (
      <iframe
        className="original-html-preview"
        title="Sandboxed HTML document preview"
        sandbox=""
        srcDoc={preview.html}
      />
    );
  }

  if (preview.kind === "csv") {
    return (
      <>
        <PreviewTable rows={preview.rows} label="CSV preview" />
        {preview.truncated && (
          <p className="original-preview-note">
            Preview limited to the first 1,000 rows and 100 columns.
          </p>
        )}
      </>
    );
  }

  if (preview.kind === "pptx") {
    return (
      <div className="original-slide-list">
        {preview.slides.map((slide) => (
          <section
            className="original-slide"
            key={`slide-${slide.number}`}
          >
            <h2>Slide {slide.number}</h2>
            {slide.paragraphs.length ? (
              slide.paragraphs.map((paragraph, index) => (
                <p key={`slide-${slide.number}-text-${index}`}>
                  {paragraph}
                </p>
              ))
            ) : (
              <p className="original-preview-empty">
                No slide text is available.
              </p>
            )}
          </section>
        ))}
        {preview.truncated && (
          <p className="original-preview-note">
            Preview limited to the first 200 slides.
          </p>
        )}
      </div>
    );
  }

  if (preview.kind === "xlsx") {
    return (
      <div className="original-sheet-list">
        {preview.sheets.map((sheet, index) => (
          <section className="original-sheet" key={`${index}-${sheet.name}`}>
            <h2>{sheet.name}</h2>
            <PreviewTable rows={sheet.rows} label={`${sheet.name} preview`} />
            {sheet.truncated && (
              <p className="original-preview-note">
                Preview limited to the first 1,000 rows and 100 columns.
              </p>
            )}
          </section>
        ))}
        {preview.sheets.length === 0 && (
          <p className="original-preview-empty">
            This workbook contains no readable worksheets.
          </p>
        )}
      </div>
    );
  }

  if (preview.kind === "markdown") {
    return <MarkdownPreview text={preview.text} />;
  }

  if (preview.kind === "unsupported") {
    return (
      <div className="original-preview-empty" role="status">
        {preview.message}
      </div>
    );
  }

  return <pre className="original-text-preview">{preview.text}</pre>;
}

export default function OriginalFileViewer({
  documentId,
  filename,
  format,
  onBack,
}) {
  const [loadState, setLoadState] = useState(null);
  const formatLabel = FORMAT_LABELS[format] || "Document";
  const identity = `${documentId ?? ""}:${format}`;
  const state =
    loadState?.identity === identity ? loadState : null;

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    async function loadPreview() {
      try {
        const { bytes } = await fetchOriginalDocument(documentId, {
          signal: controller.signal,
          formatName: formatLabel,
        });
        const preview = await buildDocumentPreview(bytes, format);
        if (active) {
          setLoadState({ identity, status: "ready", preview });
        }
      } catch (error) {
        if (active && error?.name !== "AbortError") {
          setLoadState({
            identity,
            status: "error",
            error: error?.message || "Could not preview this file.",
          });
        }
      }
    }

    void loadPreview();
    return () => {
      active = false;
      controller.abort();
    };
  }, [documentId, format, formatLabel, identity]);

  const empty = state?.status === "ready" && (
    (state.preview.kind === "text" ||
      state.preview.kind === "markdown") &&
    !state.preview.text.trim() ||
    (state.preview.kind === "csv" && state.preview.rows.length === 0) ||
    (state.preview.kind === "pptx" && state.preview.slides.length === 0) ||
    (state.preview.kind === "xlsx" &&
      state.preview.sheets.every((sheet) => sheet.rows.length === 0))
  );

  return (
    <main className="original-file-viewer">
      <header className="original-file-toolbar">
        <button
          type="button"
          className="docx-back-button"
          onClick={onBack}
        >
          ← Back to Chat
        </button>
        <div className="docx-document-title">
          <strong>{filename || "Original document"}</strong>
          <span>{formatLabel} · Original file preview</span>
        </div>
      </header>

      <div className="original-file-content">
        {!state && (
          <div className="docx-viewer-status" role="status">
            <span className="tiny-spinner" />
            Loading original {formatLabel}...
          </div>
        )}
        {state?.status === "error" && (
          <div className="docx-viewer-error" role="alert">
            <strong>Could not display this file</strong>
            <p>{state.error}</p>
          </div>
        )}
        {empty && (
          <div className="original-preview-empty">
            This document is empty.
          </div>
        )}
        {state?.status === "ready" && !empty && (
          <DocumentPreviewContent preview={state.preview} />
        )}
      </div>
    </main>
  );
}
