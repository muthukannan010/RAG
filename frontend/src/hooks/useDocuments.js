import { useCallback, useRef, useState } from "react";

import {
  API_ENDPOINTS,
  APP_CONFIG,
  buildDocumentPath,
} from "../config/endpoint";

import {
  apiRequest,
  apiUrl,
  readXhrResponse,
  getErrorMessage,
} from "../api/client";

import {
  extractDocuments,
  normalizeDocument,
} from "../utils/normal";

import { logError } from "../utils/logger";

export default function useDocuments() {
  const [documents, setDocuments] = useState([]);
  const [isLoadingDocuments, setIsLoadingDocuments] = useState(true);
  const [listError, setListError] = useState("");

  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  const [deletingId, setDeletingId] = useState(null);
  const [notice, setNotice] = useState("");

  // Prevent simultaneous upload/delete operations.
  const operationInProgress = useRef(false);

  const loadDocuments = useCallback(async () => {
    setIsLoadingDocuments(true);
    setListError("");

    try {
      const payload = await apiRequest(API_ENDPOINTS.documents);

      const items = extractDocuments(payload);
      const normalized = items.map(normalizeDocument);

      setDocuments(normalized);

      return normalized;
    } catch (error) {
      setListError(error.message);
      logError("Failed to load documents", {
        message: error.message,
      });

      return null;
    } finally {
      setIsLoadingDocuments(false);
    }
  }, []);

  const uploadPDF = useCallback(
    (file, targetDocumentId = null) => {
      if (operationInProgress.current) {
        return;
      }

      if (!file) {
        return;
      }

      if (!file.name.toLowerCase().endsWith(".pdf")) {
        setNotice("Please select a PDF document.");
        return;
      }

      if (file.size === 0) {
        setNotice("The selected PDF is empty.");
        return;
      }

      if (
        file.size >
        APP_CONFIG.maxUploadMB * 1024 * 1024
      ) {
        setNotice(
          `The maximum upload size is ${APP_CONFIG.maxUploadMB} MB.`
        );
        return;
      }

      if (
        targetDocumentId !== null &&
        !documents.some(
          (document) =>
            document.id === String(targetDocumentId)
        )
      ) {
        setNotice(
          "The document to replace was not found. Refresh the list."
        );
        return;
      }

      const replacing = targetDocumentId !== null;

      const path = replacing
        ? buildDocumentPath(
            API_ENDPOINTS.replaceDocument,
            targetDocumentId
          )
        : API_ENDPOINTS.upload;

      const method = replacing ? "PUT" : "POST";

      const formData = new FormData();
      formData.append("file", file);

      operationInProgress.current = true;

      setIsUploading(true);
      setUploadProgress(0);
      setNotice("");

      const xhr = new XMLHttpRequest();

      xhr.open(method, apiUrl(path));

      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const percentage = Math.round(
            (event.loaded / event.total) * 100
          );

          setUploadProgress(percentage);
        }
      };

      xhr.onload = async () => {
        const payload = readXhrResponse(xhr);

        try {
          if (xhr.status >= 200 && xhr.status < 300) {
            setNotice(
              payload.message ||
                (replacing
                  ? "The replacement request succeeded."
                  : "The upload request succeeded.")
            );

            // Keep the library synchronized with persisted state.
            await loadDocuments();
          } else {
            const message = getErrorMessage(
              payload,
              `HTTP ${xhr.status}: upload failed.`
            );

            setNotice(message);

            logError("Document upload failed", {
              method,
              path,
              status: xhr.status,
              message,
            });
          }
        } finally {
          operationInProgress.current = false;
          setIsUploading(false);
        }
      };

      xhr.onerror = () => {
        operationInProgress.current = false;
        setIsUploading(false);

        setNotice(
          "Cannot connect to the backend. Check that FastAPI is running."
        );

        logError("Document upload connection failed", {
          method,
          path,
        });
      };

      xhr.onabort = () => {
        operationInProgress.current = false;
        setIsUploading(false);
        setNotice("The upload request was cancelled.");
      };

      try {
        // Do not set Content-Type manually for FormData.
        xhr.send(formData);
      } catch (error) {
        operationInProgress.current = false;
        setIsUploading(false);

        setNotice("Unable to start the upload request.");

        logError("Could not start document upload", {
          message: error.message,
        });
      }
    },
    [documents, loadDocuments]
  );

  const deleteDocument = useCallback(
    async (document) => {
      if (
        !document.id ||
        operationInProgress.current
      ) {
        return;
      }

      const confirmed = window.confirm(
        `Delete "${document.filename}"?\n\n` +
          "The backend must remove the PDF and all associated " +
          "chunks, embeddings and search-index records."
      );

      if (!confirmed) {
        return;
      }

      const path = buildDocumentPath(
        API_ENDPOINTS.deleteDocument,
        document.id
      );

      operationInProgress.current = true;
      setDeletingId(document.id);
      setNotice("");

      try {
        await apiRequest(path, {
          method: "DELETE",
        });

        setDocuments((current) =>
          current.filter(
            (item) => item.id !== document.id
          )
        );

        setNotice(`Deleted ${document.filename}.`);

        // Refresh from the actual server state.
        await loadDocuments();
      } catch (error) {
        setNotice(`Delete failed: ${error.message}`);

        logError("Document deletion failed", {
          documentId: document.id,
          message: error.message,
        });
      } finally {
        operationInProgress.current = false;
        setDeletingId(null);
      }
    },
    [loadDocuments]
  );

  const clearNotice = useCallback(() => {
    setNotice("");
  }, []);

  return {
    documents,
    isLoadingDocuments,
    listError,

    isUploading,
    uploadProgress,
    deletingId,

    notice,
    clearNotice,

    loadDocuments,
    uploadPDF,
    deleteDocument,
  };
}