import { renderAsync } from "docx-preview";

import { fetchOriginalDocument } from "./originalDocument.js";

export const DOCX_MIME_TYPE =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

const DOCX_RENDER_OPTIONS = {
  breakPages: true,
  renderHeaders: true,
  renderFooters: true,
  renderFootnotes: true,
  renderEndnotes: true,
  renderAltChunks: false,
  useBase64URL: true,
};

export function getDocxViewerStatus(
  documentId,
  viewerIdentity,
  loadState
) {
  if (!documentId) {
    return {
      status: "error",
      error: "This citation does not include a document ID.",
    };
  }
  if (loadState?.identity !== viewerIdentity) {
    return { status: "loading", error: "" };
  }
  return {
    status: loadState.status,
    error: loadState.error || "",
  };
}

export async function fetchOriginalDocx(
  documentId,
  options = {}
) {
  const { bytes } = await fetchOriginalDocument(documentId, {
    ...options,
    expectedMimeType: DOCX_MIME_TYPE,
    formatName: "DOCX",
  });
  return bytes;
}

export async function renderOriginalDocx(
  documentId,
  bodyContainer,
  styleContainer,
  options = {}
) {
  const {
    signal,
    fetchImpl = globalThis.fetch,
    renderDocument = renderAsync,
  } = options;
  const document = await fetchOriginalDocument(documentId, {
    signal,
    fetchImpl,
    expectedMimeType: DOCX_MIME_TYPE,
    formatName: "DOCX",
  });
  const { bytes } = document;
  await renderDocument(
    bytes,
    bodyContainer,
    styleContainer,
    { ...DOCX_RENDER_OPTIONS }
  );
  return {
    bytes,
    documentVersionId: document.documentVersionId,
  };
}
