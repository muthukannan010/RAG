import { useCallback, useEffect, useRef, useState } from "react";

import "./app.css";

import { API_ENDPOINTS } from "./config/endpoint";
import { apiRequest } from "./api/client";
import { logError } from "./utils/logger";

import Sidebar from "./components/Sidebar";
import ChatPanel from "./components/ChatPanel";
import PDFViewer from "./components/PDFViewer";

import useDocuments from "./hooks/useDocuments";
import useSearch from "./hooks/useSearch";

function getViewerFromLocation() {
  const match = window.location.pathname.match(
    /^\/documents\/([^/]+)\/view\/?$/
  );
  if (!match) {
    return null;
  }

  const stateSource = window.history.state?.pdfViewer;
  if (stateSource?.documentId === decodeURIComponent(match[1])) {
    return stateSource;
  }

  const params = new URLSearchParams(window.location.search);
  return {
    documentId: decodeURIComponent(match[1]),
    page: Number(params.get("page")) || 1,
    sourceRef: params.get("citation"),
    filename: "PDF document",
    quotedText: null,
  };
}

function App() {
  const fileInputRef = useRef(null);

  const [apiStatus, setApiStatus] = useState("checking");
  const [question, setQuestion] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [uploadTargetId, setUploadTargetId] = useState(null);
  const [localNotice, setLocalNotice] = useState("");
  const [viewerSource, setViewerSource] = useState(
    getViewerFromLocation
  );

  const documentState = useDocuments();
  const searchState = useSearch();

  const {
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
  } = documentState;

  const {
    messages,
    isSearching,
    sendQuestion,
    clearConversation,
  } = searchState;

  const isBusy =
    isUploading ||
    isSearching ||
    deletingId !== null;

  const refreshDocuments = useCallback(() => {
    void loadDocuments();
  }, [loadDocuments]);

  // Load the document list once the component mounts.
  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  useEffect(() => {
    function handleHistoryChange() {
      setViewerSource(getViewerFromLocation());
    }

    window.addEventListener("popstate", handleHistoryChange);
    return () =>
      window.removeEventListener("popstate", handleHistoryChange);
  }, []);

  // Check backend health and recheck periodically.
  useEffect(() => {
    let active = true;

    async function checkHealth() {
      try {
        await apiRequest(API_ENDPOINTS.health);

        if (active) {
          setApiStatus("online");
        }
      } catch (error) {
        if (active) {
          setApiStatus("offline");
        }

        logError("Backend health check failed", {
          message: error.message,
        });
      }
    }

    void checkHealth();

    const timer = window.setInterval(
      checkHealth,
      45000000000
    );

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  // Open the file picker for a new document.
  function openUploadPicker() {
    if (isBusy) return;

    setUploadTargetId(null);
    setLocalNotice("");
    fileInputRef.current?.click();
  }

  // Open the picker for replacing a specific document.
  function replaceDocument(document) {
    if (isBusy || !document.id) {
      return;
    }

    const confirmed = window.confirm(
      `Replace "${document.filename}" with a new PDF?`
    );

    if (!confirmed) {
      return;
    }

    setUploadTargetId(document.id);
    setLocalNotice("");
    fileInputRef.current?.click();
  }

  // The actual file is supplied dynamically by the user.
  function handleFileChange(event) {
    const file = event.target.files?.[0];
    const targetId = uploadTargetId;

    // Reset so that the same PDF can be selected again.
    event.target.value = "";
    setUploadTargetId(null);

    if (!file) {
      return;
    }

    uploadPDF(file, targetId);
  }

  function startNewConversation() {
    if (
      messages.length > 0 &&
      !window.confirm(
        "Start a new conversation and clear these messages?"
      )
    ) {
      return;
    }

    clearConversation();
    setQuestion("");
  }

  // Keep the PDF viewer inside this app so chat state remains mounted.
  function openSource(source) {
    const page = Number(source.page);
    if (
      !source.documentId ||
      !Number.isInteger(page) ||
      page < 1
    ) {
      setLocalNotice(
        "This source does not include a valid document and page."
      );
      return;
    }

    try {
      const viewer = { ...source, page };
      const url = new URL(
        `/documents/${encodeURIComponent(source.documentId)}/view`,
        window.location.origin
      );
      url.searchParams.set("page", String(page));
      if (source.sourceRef) {
        url.searchParams.set("citation", source.sourceRef);
      }

      window.history.pushState(
        { pdfViewer: viewer },
        "",
        `${url.pathname}${url.search}`
      );
      setViewerSource(viewer);
    } catch (error) {
      logError("Could not open cited PDF page", {
        message: error.message,
      });

      setLocalNotice("Could not open the cited PDF page.");
    }
  }

  function returnToChat() {
    if (window.history.state?.pdfViewer) {
      window.history.back();
      return;
    }

    window.history.replaceState(null, "", "/");
    setViewerSource(null);
  }

  function dismissNotice() {
    setLocalNotice("");
    clearNotice();
  }

  return (
    <div className="rag-app">
      <header className="topbar">
        <div className="app-heading">
          <strong>RAG</strong>

          <span>
            Retrieval-Augmented Generation using Ollama
          </span>
        </div>
      </header>

      <div className="workspace">
        {viewerSource ? (
          <PDFViewer
            source={viewerSource}
            onBack={returnToChat}
          />
        ) : (
          <>
            <Sidebar
              documents={documents}
              isLoadingDocuments={isLoadingDocuments}
              listError={listError}
              onRefresh={refreshDocuments}
              onUploadClick={openUploadPicker}
              onReplaceDocument={replaceDocument}
              onDeleteDocument={deleteDocument}
              isBusy={isBusy}
              isUploading={isUploading}
              uploadProgress={uploadProgress}
              deletingId={deletingId}
              notice={localNotice || notice}
              onDismissNotice={dismissNotice}
            />

            <ChatPanel
              messages={messages}
              question={question}
              onQuestionChange={setQuestion}
              onSendQuestion={sendQuestion}
              isSearching={isSearching}
              isBusy={isBusy}
              onUploadClick={openUploadPicker}
              onOpenSource={openSource}
              onNewConversation={startNewConversation}
              apiStatus={apiStatus}
              settingsOpen={settingsOpen}
              onToggleSettings={() =>
                setSettingsOpen((current) => !current)
              }
            />
          </>
        )}
      </div>

      <input
        ref={fileInputRef}
        className="hidden-file-input"
        type="file"
        accept=".pdf,application/pdf"
        onChange={handleFileChange}
        disabled={isBusy}
        aria-label="Select a PDF document"
      />
    </div>
  );
}

export default App;