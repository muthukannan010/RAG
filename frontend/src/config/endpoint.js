const env = import.meta.env;

export const API_BASE_URL = (
  env.VITE_API_BASE_URL || ""
).replace(/\/+$/, "");

export const API_ENDPOINTS = {
  health: env.VITE_HEALTH_ENDPOINT || "/api/v1/health",

  documents:
    env.VITE_DOCUMENTS_ENDPOINT || "/api/v1/documents",

  upload:
    env.VITE_UPLOAD_ENDPOINT || "/api/v1/documents/upload",

  search:
    env.VITE_SEARCH_ENDPOINT || "/api/v1/search",

  deleteDocument:
    env.VITE_DELETE_ENDPOINT_TEMPLATE ||
    "/api/v1/documents/{id}",

  replaceDocument:
    env.VITE_REPLACE_ENDPOINT_TEMPLATE ||
    "/api/v1/documents/{id}",

  pdf:
    env.VITE_PDF_ENDPOINT_TEMPLATE ||
    "/api/v1/documents/{id}/file",
};

export const APP_CONFIG = {
  maxUploadMB: Number(env.VITE_MAX_UPLOAD_MB || 50),
  searchField: env.VITE_SEARCH_FIELD || "query",
};

export function buildDocumentPath(template, documentId) {
  return template.replace(
    "{id}",
    encodeURIComponent(String(documentId))
  );
}