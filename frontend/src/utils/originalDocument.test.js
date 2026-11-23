import assert from "node:assert/strict";
import test from "node:test";

import { API_ENDPOINTS } from "../config/endpoint.js";
import { fetchOriginalDocument } from "./originalDocument.js";

test("fetches original bytes and optional served version identity", async () => {
  const bytes = new Uint8Array([1, 2, 3]).buffer;
  let requestUrl;
  const result = await fetchOriginalDocument("doc-1", {
    fetchImpl: async (url) => {
      requestUrl = url;
      return {
        ok: true,
        headers: {
          get(name) {
            if (name === "content-type") {
              return "text/plain; charset=utf-8";
            }
            if (name === "x-document-version-id") {
              return "version-current";
            }
            return null;
          },
        },
        arrayBuffer: async () => bytes,
      };
    },
  });

  assert.equal(
    requestUrl,
    API_ENDPOINTS.documentFile.replace("{id}", "doc-1")
  );
  assert.strictEqual(result.bytes, bytes);
  assert.equal(result.mimeType, "text/plain");
  assert.equal(result.documentVersionId, "version-current");
});

test("fails explicitly for missing documents and failed downloads", async () => {
  await assert.rejects(
    fetchOriginalDocument("", { fetchImpl: async () => ({}) }),
    /document ID/
  );
  await assert.rejects(
    fetchOriginalDocument("missing", {
      fetchImpl: async () => ({
        ok: false,
        status: 404,
        headers: { get: () => null },
        json: async () => ({ detail: "Document not found." }),
      }),
    }),
    /Document not found/
  );
});
