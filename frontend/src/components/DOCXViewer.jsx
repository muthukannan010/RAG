import { useEffect, useRef, useState } from "react";

import {
  getDocxViewerStatus,
  renderOriginalDocx,
} from "../utils/docxViewer";
import {
  buildDocxStructuralIndex,
  mapDocxLocatorsToDom,
} from "../utils/docxDomMapping";
import {
  applyDocxCitationHighlights,
  clearDocxCitationHighlights,
  scrollToDocxCitationSegment,
} from "../utils/docxCitationHighlight";

const EMPTY_LOCATOR_SEGMENTS = [];

function unresolvedMappings(locatorSegments, reason) {
  return locatorSegments.map((locator) => ({
    locatorPath: locator?.structural_path || [],
    stableKey: null,
    domElement: null,
    domCell: null,
    canonicalTextMapping: null,
    textNodeRanges: [],
    mappingStatus: "unresolved",
    diagnosticReason: reason,
  }));
}

function getLocationMessage(mappingState, mappingError) {
  const mappings = mappingState?.mappings || [];
  const resolvedCount = mappings.filter(
    (mapping) => mapping.mappingStatus === "resolved"
  ).length;
  const unresolvedCount = mappings.length - resolvedCount;
  const isAmbiguous = mappings.some(
    (mapping) => mapping.mappingStatus === "ambiguous"
  );
  const diagnostics = mappings
    .map((mapping) => mapping.diagnosticReason)
    .filter(Boolean);

  if (
    diagnostics.some((reason) =>
      reason.includes("different document version")
    )
  ) {
    return "This citation belongs to a different document version. No passage was highlighted.";
  }
  if (
    diagnostics.some((reason) =>
      reason.includes("served document version could not be verified")
    )
  ) {
    return "The document service did not identify the version it served, so this citation location cannot be verified or highlighted.";
  }
  if (resolvedCount > 0 && unresolvedCount > 0) {
    return `${resolvedCount} citation segment(s) were verified; ${unresolvedCount} could not be verified. Only verified segments are highlighted.`;
  }
  if (resolvedCount > 0) {
    return "Citation location verified and highlighted.";
  }
  if (isAmbiguous) {
    return "Multiple document locations match this citation. No arbitrary location was selected.";
  }
  if (diagnostics.some((reason) => reason.includes("ambiguous"))) {
    return "Multiple document locations match this citation. No arbitrary location was selected.";
  }
  return (
    mappingError ||
    diagnostics[0] ||
    "Citation location could not be verified. The document is shown without a selected passage."
  );
}

export default function DOCXViewer({ source, onBack }) {
  const documentId = source?.documentId;
  const versionId = source?.versionId ?? "";
  const filename =
    typeof source?.filename === "string" ? source.filename : "";
  const viewerIdentity = `${documentId ?? ""}:${versionId}`;
  const locatorSegments = Array.isArray(source?.locatorSegments)
    ? source.locatorSegments
    : EMPTY_LOCATOR_SEGMENTS;
  const locatorKey = JSON.stringify(locatorSegments);
  const [loadState, setLoadState] = useState(null);
  const [mappingState, setMappingState] = useState(null);
  const [activeSegment, setActiveSegment] = useState(0);
  const bodyRef = useRef(null);
  const styleRef = useRef(null);

  const { status, error } = getDocxViewerStatus(
    documentId,
    viewerIdentity,
    loadState
  );
  const currentMappingState =
    mappingState?.identity === viewerIdentity &&
    mappingState?.locatorKey === locatorKey
      ? mappingState
      : null;
  const resolvedMappings =
    currentMappingState?.mappings?.filter(
      (mapping) =>
        mapping.mappingStatus === "resolved" && mapping.domElement
    ) || [];

  useEffect(() => {
    if (!documentId) {
      return undefined;
    }

    const bodyContainer = bodyRef.current;
    const styleContainer = styleRef.current;
    if (!bodyContainer || !styleContainer) {
      return undefined;
    }

    const controller = new AbortController();
    const stagingBody = document.createElement("div");
    const stagingStyles = document.createElement("div");
    let active = true;

    async function loadAndRender() {
      try {
        const document = await renderOriginalDocx(
          documentId,
          stagingBody,
          stagingStyles,
          { signal: controller.signal }
        );
        if (!active) {
          return;
        }

        let structuralIndex = null;
        let mappingError = "";
        try {
          structuralIndex = await buildDocxStructuralIndex(
            document.bytes
          );
        } catch (indexError) {
          mappingError =
            indexError?.message ||
            "Could not inspect the DOCX structure for citation mapping.";
        }
        if (!active) {
          return;
        }

        styleContainer.replaceChildren(...stagingStyles.childNodes);
        bodyContainer.replaceChildren(...stagingBody.childNodes);
        setLoadState({
          identity: viewerIdentity,
          status: "ready",
          structuralIndex,
          documentVersionId: document.documentVersionId,
          mappingError,
        });
      } catch (loadError) {
        if (active && loadError?.name !== "AbortError") {
          setLoadState({
            identity: viewerIdentity,
            status: "error",
            error: loadError?.message || "Could not render this DOCX.",
          });
        }
      } finally {
        stagingBody.replaceChildren();
        stagingStyles.replaceChildren();
      }
    }

    void loadAndRender();

    return () => {
      active = false;
      controller.abort();
      clearDocxCitationHighlights(bodyContainer);
      bodyContainer.replaceChildren();
      styleContainer.replaceChildren();
      stagingBody.replaceChildren();
      stagingStyles.replaceChildren();
    };
  }, [documentId, viewerIdentity]);

  useEffect(() => {
    const bodyContainer = bodyRef.current;
    if (
      !bodyContainer ||
      status !== "ready" ||
      loadState?.identity !== viewerIdentity
    ) {
      return undefined;
    }

    clearDocxCitationHighlights(bodyContainer);
    queueMicrotask(() => setActiveSegment(0));

    if (locatorSegments.length === 0) {
      queueMicrotask(() =>
        setMappingState({
          identity: viewerIdentity,
          locatorKey,
          mappings: [],
        })
      );
      return undefined;
    }

    let mappings;
    if (!loadState.structuralIndex) {
      mappings = unresolvedMappings(
        locatorSegments,
        loadState.mappingError ||
          "The DOCX structure could not be inspected."
      );
    } else {
      try {
        mappings = mapDocxLocatorsToDom({
          renderedRoot: bodyContainer,
          structuralIndex: loadState.structuralIndex,
          locatorSegments,
          documentVersionId: loadState.documentVersionId,
        });
      } catch (mappingError) {
        mappings = unresolvedMappings(
          locatorSegments,
          mappingError?.message ||
            "Could not verify DOCX citation locations."
        );
      }
    }

    const highlight = applyDocxCitationHighlights(
      bodyContainer,
      mappings
    );
    queueMicrotask(() =>
      setMappingState({
        identity: viewerIdentity,
        locatorKey,
        mappings,
        highlighted: highlight.highlighted,
      })
    );

    return () => clearDocxCitationHighlights(bodyContainer);
  }, [
    loadState,
    locatorKey,
    locatorSegments,
    status,
    viewerIdentity,
  ]);

  const locationMessage = locatorSegments.length > 0
    ? getLocationMessage(
        currentMappingState,
        loadState?.mappingError
      )
    : "";

  return (
    <main className="docx-viewer">
      <header className="docx-viewer-toolbar">
        <button
          type="button"
          className="docx-back-button"
          onClick={onBack}
        >
          ← Back to Chat
        </button>

        <div className="docx-document-title">
          <strong>{filename || "DOCX document"}</strong>
          <span>
            {source?.sourceRef
              ? `Citation [${source.sourceRef}] · `
              : ""}
            Original DOCX Preview
          </span>
        </div>
      </header>

      <div className="docx-preview-scroll">
        {status === "loading" && (
          <div className="docx-viewer-status" role="status">
            <span className="tiny-spinner" />
            Loading original DOCX...
          </div>
        )}
        {status === "error" && (
          <div className="docx-viewer-error" role="alert">
            <strong>Could not display this DOCX</strong>
            <p>{error}</p>
          </div>
        )}
        {status === "ready" && currentMappingState && (
          <>
            {resolvedMappings.length > 1 && (
              <nav
                className="docx-citation-navigation"
                aria-label="Citation segments"
              >
                <span>
                  {resolvedMappings.length} verified citation segments
                </span>
                {resolvedMappings.map((mapping, index) => (
                  <button
                    type="button"
                    key={`${mapping.stableKey}-${index}`}
                    aria-current={activeSegment === index}
                    onClick={() => {
                      setActiveSegment(index);
                      scrollToDocxCitationSegment(mapping);
                    }}
                  >
                    Segment {index + 1}
                  </button>
                ))}
              </nav>
            )}
            {locationMessage && (
              <div className="docx-locator-status" role="status">
                {locationMessage}
              </div>
            )}
          </>
        )}
        <div
          className="docx-preview-styles"
          ref={styleRef}
          aria-hidden="true"
        />
        <div
          className="docx-preview-content"
          ref={bodyRef}
          aria-label="Original DOCX preview"
          hidden={status !== "ready"}
        />
      </div>
    </main>
  );
}
