import assert from "node:assert/strict";
import test from "node:test";

import { API_ENDPOINTS } from "../config/endpoint.js";
import {
  DOCX_MIME_TYPE,
  fetchOriginalDocx,
  getDocxViewerStatus,
  renderOriginalDocx,
} from "./docxViewer.js";

function response({
  ok = true,
  status = 200,
  contentType = DOCX_MIME_TYPE,
  bytes = new Uint8Array([1, 2, 3]).buffer,
  payload = {},
} = {}) {
  return {
    ok,
    status,
    headers: {
      get(name) {
        return name.toLowerCase() === "content-type"
          ? contentType
          : null;
      },
    },
    async arrayBuffer() {
      return bytes;
    },
    async json() {
      return payload;
    },
  };
}

test("fetches original DOCX bytes from the configured file endpoint", async () => {
  const bytes = new Uint8Array([80, 75, 3, 4]).buffer;
  let requestUrl;
  let requestOptions;

  const result = await fetchOriginalDocx("doc/one", {
    fetchImpl: async (url, options) => {
      requestUrl = url;
      requestOptions = options;
      return response({ bytes });
    },
  });

  assert.equal(
    requestUrl,
    API_ENDPOINTS.documentFile.replace("{id}", "doc%2Fone")
  );
  assert.equal(requestOptions.headers.Accept, DOCX_MIME_TYPE);
  assert.strictEqual(result, bytes);
});

test("passes original bytes and renderer options into local rendering", async () => {
  const bytes = new Uint8Array([80, 75, 3, 4]).buffer;
  const bodyContainer = {};
  const styleContainer = {};
  let renderArguments;

  const result = await renderOriginalDocx(
    "doc-1",
    bodyContainer,
    styleContainer,
    {
      fetchImpl: async () => response({ bytes }),
      renderDocument: async (...args) => {
        renderArguments = args;
      },
    }
  );

  assert.strictEqual(renderArguments[0], bytes);
  assert.strictEqual(renderArguments[1], bodyContainer);
  assert.strictEqual(renderArguments[2], styleContainer);
  assert.equal(renderArguments[3].useBase64URL, true);
  assert.equal(renderArguments[3].renderAltChunks, false);
  assert.strictEqual(result.bytes, bytes);
  assert.equal(result.documentVersionId, null);
});

test("reports missing files and rejects non-DOCX responses", async () => {
  await assert.rejects(
    fetchOriginalDocx("missing", {
      fetchImpl: async () =>
        response({
          ok: false,
          status: 404,
          payload: { detail: "Document not found." },
        }),
    }),
    /Document not found/
  );

  await assert.rejects(
    fetchOriginalDocx("doc-1", {
      fetchImpl: async () =>
        response({ contentType: "application/pdf" }),
    }),
    /did not return a DOCX/
  );
});

test("models loading, error, and stale-document states", () => {
  assert.deepEqual(
    getDocxViewerStatus("doc-1", "doc-1:v1", null),
    { status: "loading", error: "" }
  );
  assert.deepEqual(
    getDocxViewerStatus("doc-1", "doc-1:v1", {
      identity: "doc-1:v1",
      status: "error",
      error: "Render failed.",
    }),
    { status: "error", error: "Render failed." }
  );
  assert.deepEqual(
    getDocxViewerStatus("doc-2", "doc-2:v2", {
      identity: "doc-1:v1",
      status: "ready",
    }),
    { status: "loading", error: "" }
  );
  assert.equal(
    getDocxViewerStatus(null, ":", null).status,
    "error"
  );
});