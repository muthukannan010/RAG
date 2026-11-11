import { useEffect, useRef, useState } from "react";

import { apiUrl } from "../api/client";
import { API_ENDPOINTS, buildDocumentPath } from "../config/endpoint";

function getErrorMessage(payload, fallback) {
  if (typeof payload?.detail === "string") {
    return payload.detail;
  }
  return fallback;
}

export default function PDFViewer({ source, onBack }) {
  const firstPage = Number(source.page);
  const [page, setPage] = useState(
    Number.isInteger(firstPage) && firstPage > 0 ? firstPage : 1
  );
  const [pageCount, setPageCount] = useState(null);
  const [zoom, setZoom] = useState(100);
  const [pageImage, setPageImage] = useState(null);
  const [highlightMatched, setHighlightMatched] = useState(false);
  const [highlightY, setHighlightY] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const scrollRef = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    let imageUrl = null;
    const quotedText =
      page === Number(source.page) ? source.quotedText : null;

    async function loadPage() {
      setIsLoading(true);
      setError("");
      setPageImage(null);
      setHighlightMatched(false);
      setHighlightY(null);

      const path = buildDocumentPath(
        API_ENDPOINTS.pdfPagePreview,
        source.documentId
      ).replace("{page}", encodeURIComponent(String(page)));

      try {
        const response = await fetch(apiUrl(path), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            quoted_text: quotedText || null,
          }),
          signal: controller.signal,
        });

        if (!response.ok) {
          let payload = {};
          try {
            payload = await response.json();
          } catch {
            // Use the status message when the server response is not JSON.
          }
          throw new Error(
            getErrorMessage(
              payload,
              `Could not load this PDF page (HTTP ${response.status}).`
            )
          );
        }

        const count = Number(
          response.headers.get("X-PDF-Page-Count")
        );
        if (Number.isInteger(count) && count > 0) {
          setPageCount(count);
        }
        setHighlightMatched(
          response.headers.get("X-PDF-Highlight-Matched") === "true"
        );
        const highlightYHeader =
          response.headers.get("X-PDF-Highlight-Y");
        const parsedHighlightY = Number(highlightYHeader);
        setHighlightY(
          highlightYHeader && Number.isFinite(parsedHighlightY)
            ? Math.min(1, Math.max(0, parsedHighlightY))
            : null
        );

        imageUrl = URL.createObjectURL(await response.blob());
        setPageImage(imageUrl);
      } catch (loadError) {
        if (loadError.name !== "AbortError") {
          setError(loadError.message);
        }
      } finally {
        if (!controller.signal.aborted) {
          setIsLoading(false);
        }
      }
    }

    if (!source.documentId) {
      setError("This citation does not include a document ID.");
      setIsLoading(false);
    } else {
      void loadPage();
    }

    return () => {
      controller.abort();
      if (imageUrl) {
        URL.revokeObjectURL(imageUrl);
      }
    };
  }, [page, source.documentId, source.page, source.quotedText]);

  function changeZoom(amount) {
    setZoom((current) =>
      Math.min(200, Math.max(50, current + amount))
    );
  }

  function scrollToHighlight(event) {
    if (!highlightMatched || highlightY == null) {
      return;
    }

    const container = scrollRef.current;
    const image = event.currentTarget;
    if (!container) {
      return;
    }

    const imageRect = image.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();
    const imageTop = container.scrollTop
      + imageRect.top
      - containerRect.top;
    container.scrollTo({
      top:
        imageTop
        + image.clientHeight * highlightY
        - container.clientHeight * 0.35,
      behavior: "smooth",
    });
  }

  const isCitationPage = page === Number(source.page);
  const supportingText = source.quotedText || source.text;

  return (
    <main className="pdf-viewer">
      <div className="pdf-viewer-toolbar">
        <button
          type="button"
          className="pdf-back-button"
          onClick={onBack}
        >
          ← Back to Chat
        </button>

        <div className="pdf-document-title">
          <strong>{source.filename || "PDF document"}</strong>
          {source.sourceRef && (
            <span>
              Citation [{source.sourceRef}]
              {isCitationPage ? ` · Page ${source.page}` : ""}
            </span>
          )}
        </div>

        <div className="pdf-controls">
          <button
            type="button"
            onClick={() => setPage((current) => Math.max(1, current - 1))}
            disabled={page <= 1 || isLoading}
            aria-label="Previous page"
          >
            Previous
          </button>
          <span className="pdf-page-count">
            Page {page}{pageCount ? ` of ${pageCount}` : ""}
          </span>
          <button
            type="button"
            onClick={() =>
              setPage((current) =>
                pageCount ? Math.min(pageCount, current + 1) : current + 1
              )
            }
            disabled={
              isLoading || (pageCount !== null && page >= pageCount)
            }
            aria-label="Next page"
          >
            Next
          </button>
          <span className="pdf-control-divider" />
          <button
            type="button"
            onClick={() => changeZoom(-10)}
            disabled={zoom <= 50}
            aria-label="Zoom out"
          >
            −
          </button>
          <span className="pdf-zoom-value">{zoom}%</span>
          <button
            type="button"
            onClick={() => changeZoom(10)}
            disabled={zoom >= 200}
            aria-label="Zoom in"
          >
            +
          </button>
          <button
            type="button"
            onClick={() => setZoom(100)}
            className="pdf-fit-button"
          >
            Fit width
          </button>
        </div>
      </div>

      {supportingText && (
        <aside className="pdf-citation-quote">
          <strong>
            {source.quotedText
              ? "Supporting passage"
              : "Retrieved passage"}
          </strong>
          <span>{supportingText}</span>
          {isCitationPage && !highlightMatched && !isLoading && (
            <small>
              {source.quotedText
                ? "The quotation could not be matched to PDF text. The cited page is shown without a highlight."
                : "No exact LLM quotation was verified. The cited page is shown without a highlight."}
            </small>
          )}
        </aside>
      )}

      <div className="pdf-page-scroll" ref={scrollRef}>
        {isLoading && (
          <div className="pdf-viewer-status" role="status">
            <span className="tiny-spinner" />
            Loading page...
          </div>
        )}
        {error && (
          <div className="pdf-viewer-error" role="alert">
            <strong>Could not display this PDF</strong>
            <p>{error}</p>
          </div>
        )}
        {pageImage && (
          <div
            className="pdf-page-image-frame"
            style={{ width: `${zoom}%` }}
          >
            <img
              className="pdf-page-image"
              src={pageImage}
              alt={`${source.filename || "PDF"} page ${page}`}
              onLoad={scrollToHighlight}
            />
          </div>
        )}
      </div>
    </main>
  );
}
