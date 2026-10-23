import { API_BASE_URL } from "../config/endpoint";
import { logError } from "../utils/logger";

export function apiUrl(path) {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }

  return `${API_BASE_URL}${path}`;
}

export function getErrorMessage(
  payload,
  fallback = "The request failed."
) {
  const detail = payload?.detail ?? payload?.message;

  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }

  if (detail != null) {
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }

  return fallback;
}

export async function readResponse(response) {
  const text = await response.text();

  if (!text) {
    return {};
  }

  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

export async function apiRequest(path, options = {}) {
  const url = apiUrl(path);
  const method = (options.method || "GET").toUpperCase();

  let response;

  try {
    response = await fetch(url, options);
  } catch (error) {
    logError("API connection failed", {
      method,
      path,
      message: error.message,
    });

    throw new Error(
      `Cannot connect to the backend. Check that FastAPI is running.`
    );
  }

  const payload = await readResponse(response);

  if (!response.ok) {
    const message = getErrorMessage(
      payload,
      `HTTP ${response.status}: ${response.statusText}`
    );

    logError("API request failed", {
      method,
      path,
      status: response.status,
      message,
    });

    throw new Error(message);
  }

  return payload;
}

export function readXhrResponse(xhr) {
  try {
    return JSON.parse(xhr.responseText || "{}");
  } catch {
    return {};
  }
}