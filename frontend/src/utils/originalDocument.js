import {
  API_BASE_URL,
  API_ENDPOINTS,
  buildDocumentPath,
} from "../config/endpoint.js";

async function errorResponse(response, formatName) {
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    // Use the HTTP status when the server does not return JSON.
  }

  const detail = payload?.detail ?? payload?.message;
  const message =
    typeof detail === "string" && detail.trim()
      ? detail
      : `Could not load the original ${formatName} (HTTP ${response.status}).`;
  return new Error(message);
}

export async function fetchOriginalDocument(
  documentId,
  {
    signal,
    fetchImpl = globalThis.fetch,
    expectedMimeType = null,
    formatName = "document",
  } = {}
) {
  if (typeof documentId !== "string" || !documentId.trim()) {
    throw new Error("This source does not include a document ID.");
  }
  if (typeof fetchImpl !== "function") {
    throw new Error("The browser does not support document downloads.");
  }

  const path = buildDocumentPath(
    API_ENDPOINTS.documentFile,
    documentId
  );
  const url = /^https?:\/\//i.test(path)
    ? path
    : `${API_BASE_URL}${path}`;
  let response;
  try {
    response = await fetchImpl(url, {
      headers: { Accept: expectedMimeType || "*/*" },
      signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") {
      throw error;
    }
    throw new Error(
      "Could not connect to the document service.",
      { cause: error }
    );
  }

  if (!response.ok) {
    throw await errorResponse(response, formatName);
  }

  const mimeType = response.headers
    ?.get("content-type")
    ?.split(";")[0]
    .trim()
    .toLowerCase() || "";
  if (expectedMimeType && mimeType && mimeType !== expectedMimeType) {
    throw new Error(
      `The file endpoint did not return a ${formatName} document.`
    );
  }

  return {
    bytes: await response.arrayBuffer(),
    mimeType,
    documentVersionId:
      response.headers?.get("x-document-version-id")?.trim() || null,
  };
}
