import { useCallback, useEffect, useRef, useState } from "react";
import "./App.css";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

const ENDPOINTS = {
  health: import.meta.env.VITE_HEALTH_ENDPOINT || "/api/v1/health",
  documents: import.meta.env.VITE_DOCUMENTS_ENDPOINT || "/api/v1/documents",
  upload: import.meta.env.VITE_UPLOAD_ENDPOINT || "/api/v1/documents/upload",
  search: import.meta.env.VITE_SEARCH_ENDPOINT || "/api/v1/search",
  pdf: import.meta.env.VITE_PDF_ENDPOINT_TEMPLATE ||
    "/api/v1/documents/{id}/file",
  delete: import.meta.env.VITE_DELETE_ENDPOINT_TEMPLATE ||
    "/api/v1/documents/{id}",
  maxUploadMB: Number(import.meta.env.VITE_MAX_UPLOAD_MB || 50),
  searchField: import.meta.env.VITE_SEARCH_FIELD || "query",
};

function apiUrl(path) {
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_BASE}${path}`;
}

async function readResponse(response) {
  const text = await response.text();
  if (!text) return {};

  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

function getErrorMessage(payload, fallback) {
  const detail = payload?.detail ?? payload?.message;

  if (typeof detail === "string") return detail;
  if (detail != null) return JSON.stringify(detail);

  return fallback;
}

async function apiRequest(path, options = {}) {
  const response = await fetch(apiUrl(path), options);
  const payload = await readResponse(response);

  if (!response.ok) {
    throw new Error(
      getErrorMessage(payload, `HTTP ${response.status}`)
    );
  }

  return payload;
}

function extractDocuments(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.documents)) return payload.documents;
  if (Array.isArray(payload?.items)) return payload.items;
  if (Array.isArray(payload?.data)) return payload.data;
  return [];
}

function normalizeDocument(item) {
  const rawId =
    item.document_id ?? item.id ?? item.documentId ?? item.uuid;

  return {
    id: rawId == null ? null : String(rawId),
    filename:
      item.filename ??
      item.original_filename ??
      item.document_name ??
      item.name ??
      "Untitled PDF",
    pages: item.page_count ?? item.pages ?? null,
    bytes: item.size_bytes ?? item.file_size ?? item.size ?? null,
    status: item.status ?? "Available",
  };
}

function getSearchResults(payload) {
  const data = payload?.data ?? payload;

  if (Array.isArray(data)) return data;

  return (
    data?.results ??
    data?.sources ??
    data?.chunks ??
    data?.items ??
    []
  );
}

function normalizeSource(item, index) {
  const meta = item.metadata ?? {};

  return {
    id: String(item.id ?? item.chunk_id ?? index),
    documentId:
      item.document_id ??
      item.doc_id ??
      meta.document_id ??
      null,
    filename:
      item.filename ??
      item.document_name ??
      item.source ??
      meta.filename ??
      meta.source ??
      "Source document",
    page:
      item.page_number ??
      item.page ??
      meta.page_number ??
      meta.page ??
      null,
    keyword:
      item.keyword_match_percent ??
      item.keyword_match ??
      item.keyword_score ??
      meta.keyword_match ??
      null,
    semantic:
      item.semantic_match_percent ??
      item.semantic_match ??
      item.semantic_score ??
      meta.semantic_match ??
      null,
    relevance:
      item.final_relevance ??
      item.final_score ??
      item.relevance_score ??
      item.score ??
      null,
    text:
      item.snippet ??
      item.content ??
      item.chunk_text ??
      item.text ??
      item.page_content ??
      "",
    fileUrl:
      item.file_url ??
      item.pdf_url ??
      meta.file_url ??
      null,
  };
}

function formatBytes(value) {
  if (value == null || !Number.isFinite(Number(value))) return "";

  const bytes = Number(value);

  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;

  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatPercent(value) {
  if (value == null || value === "") return "—";

  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);

  // Supports scores represented as either 0–1 or 0–100.
  const percentage =
    number >= 0 && number <= 1 ? number * 100 : number;

  return `${percentage.toFixed(
    Number.isInteger(percentage) ? 0 : 2
  )}%`;
}

const STOP_WORDS = new Set([
  "what", "when", "where", "which", "who", "whom",
  "does", "that", "this", "with", "from", "have",
  "your", "their", "there", "about", "into", "were",
  "will", "would", "could", "should", "the", "and",
  "are", "was", "for", "how", "can",
]);

function HighlightText({ text, question }) {
  if (!text) return null;

  const terms = [
    ...new Set(
      (question.match(/[a-z0-9-]+/gi) || [])
        .map((term) => term.toLowerCase())
        .filter((term) => term.length > 2 && !STOP_WORDS.has(term))
    ),
  ].sort((a, b) => b.length - a.length);

  if (!terms.length) return text;

  const escapeRegex = (value) =>
    value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  const expression = new RegExp(
    `\\b(${terms.map(escapeRegex).join("|")})\\b`,
    "gi"
  );

  return text.split(expression).map((part, index) =>
    terms.includes(part.toLowerCase()) ? (
      <mark key={`${part}-${index}`}>{part}</mark>
    ) : (
      part
    )
  );
}

function Icon({ name, size = 20 }) {
  const paths = {
    file: (
      <>
        <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
        <path d="M13 2v7h7" />
      </>
    ),
    upload: (
      <>
        <path d="M12 16V4" />
        <path d="m7 9 5-5 5 5" />
        <path d="M4 20h16" />
      </>
    ),
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    settings: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="m19.4 15 .1.1a1.7 1.7 0 0 1-2.4 2.4l-.1-.1a1.7 1.7 0 0 0-2.9 1.2v.2a1.7 1.7 0 0 1-3.4 0v-.2a1.7 1.7 0 0 0-2.9-1.2l-.1.1a1.7 1.7 0 0 1-2.4-2.4l.1-.1a1.7 1.7 0 0 0-1.2-2.9H4a1.7 1.7 0 0 1 0-3.4h.2a1.7 1.7 0 0 0 1.2-2.9l-.1-.1a1.7 1.7 0 0 1 2.4-2.4l.1.1a1.7 1.7 0 0 0 2.9-1.2V2a1.7 1.7 0 0 1 3.4 0v.2a1.7 1.7 0 0 0 2.9 1.2l.1-.1a1.7 1.7 0 0 1 2.4 2.4l-.1.1a1.7 1.7 0 0 0 1.2 2.9h.2a1.7 1.7 0 0 1 0 3.4h-.2a1.7 1.7 0 0 0-1.2 2.9Z" />
      </>
    ),
    send: (
      <>
        <path d="m22 2-7 20-4-9-9-4Z" />
        <path d="M22 2 11 13" />
      </>
    ),
    clip: (
      <>
        <path d="m21.4 11.1-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5" />
      </>
    ),
    trash: (
      <>
        <path d="M3 6h18" />
        <path d="M8 6V4h8v2" />
        <path d="m5 6 1 14h12l1-14" />
        <path d="M10 10v6M14 10v6" />
      </>
    ),
    close: <path d="m18 6-12 12M6 6l12 12" />,
    refresh: (
      <>
        <path d="M20 7v5h-5" />
        <path d="M4 17v-5h5" />
        <path d="M5.6 9A7 7 0 0 1 18 6l2 6" />
        <path d="M18.4 15A7 7 0 0 1 6 18l-2-6" />
      </>
    ),
  };

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}

function App() {
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);
  const messagesEndRef = useRef(null);

  const [documents, setDocuments] = useState([]);
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");

  const [apiStatus, setApiStatus] = useState("checking");
  const [isLoadingDocuments, setIsLoadingDocuments] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isSearching, setIsSearching] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [notice, setNotice] = useState("");

  const busy = isUploading || isSearching || deletingId !== null;

  const loadDocuments = useCallback(async () => {
    setIsLoadingDocuments(true);

    try {
      const payload = await apiRequest(ENDPOINTS.documents);
      setDocuments(extractDocuments(payload).map(normalizeDocument));
    } catch (error) {
      setNotice(`Could not load documents: ${error.message}`);
    } finally {
      setIsLoadingDocuments(false);
    }
  }, []);

  useEffect(() => {
    let active = true;

    async function checkHealth() {
      try {
        const response = await fetch(apiUrl(ENDPOINTS.health));

        if (!response.ok) throw new Error("API unavailable");

        if (active) setApiStatus("online");
      } catch {
        if (active) setApiStatus("offline");
      }
    }

    void checkHealth();
    void loadDocuments();

    const interval = window.setInterval(checkHealth, 15000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [loadDocuments]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [messages, isSearching]);

  // Add PDF by selecting a file from the user's computer.
  function choosePDF(file) {
    if (!file) return;

    setNotice("");

    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setNotice("Please select a PDF document.");
      return;
    }

    if (file.size === 0) {
      setNotice("The selected file is empty.");
      return;
    }

    if (file.size > ENDPOINTS.maxUploadMB * 1024 * 1024) {
      setNotice(
        `The maximum upload size is ${ENDPOINTS.maxUploadMB} MB.`
      );
      return;
    }

    uploadPDF(file);
  }

  function uploadPDF(file) {
    if (busy) return;

    setIsUploading(true);
    setUploadProgress(0);
    setNotice("");

    const formData = new FormData();
    formData.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", apiUrl(ENDPOINTS.upload));

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        setUploadProgress(
          Math.round((event.loaded / event.total) * 100)
        );
      }
    };

    xhr.onload = async () => {
      let payload = {};

      try {
        payload = JSON.parse(xhr.responseText || "{}");
      } catch {
        payload = {};
      }

      setIsUploading(false);

      if (xhr.status >= 200 && xhr.status < 300) {
        setNotice(payload.message || `${file.name} was uploaded.`);
        setApiStatus("online");
        await loadDocuments();
      } else {
        setNotice(
          getErrorMessage(
            payload,
            `Upload failed with HTTP ${xhr.status}.`
          )
        );
      }
    };

    xhr.onerror = () => {
      setIsUploading(false);
      setApiStatus("offline");
      setNotice("Cannot connect to FastAPI. Check the backend server.");
    };

    xhr.send(formData);
  }

  async function deleteDocument(document) {
    if (!document.id || busy) return;

    const confirmed = window.confirm(
      `Delete "${document.filename}" and its indexed data?`
    );

    if (!confirmed) return;

    setDeletingId(document.id);
    setNotice("");

    try {
      const path = ENDPOINTS.delete.replace(
        "{id}",
        encodeURIComponent(document.id)
      );

      await apiRequest(path, { method: "DELETE" });

      setDocuments((current) =>
        current.filter((item) => item.id !== document.id)
      );

      setNotice(`Deleted ${document.filename}.`);
    } catch (error) {
      setNotice(`Delete failed: ${error.message}`);
    } finally {
      setDeletingId(null);
    }
  }

  async function sendQuestion(event) {
    event?.preventDefault();

    const prompt = question.trim();

    if (!prompt || busy) return;

    setQuestion("");
    setNotice("");

    const userMessage = {
      id: `${Date.now()}-user`,
      role: "user",
      content: prompt,
    };

    setMessages((current) => [...current, userMessage]);
    setIsSearching(true);

    try {
      const payload = await apiRequest(ENDPOINTS.search, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          [ENDPOINTS.searchField]: prompt,
        }),
      });

      const results = getSearchResults(payload).map(normalizeSource);

      const rawAnswer =
        payload?.answer ??
        payload?.generated_answer ??
        payload?.response ??
        payload?.data?.answer ??
        "";

      const answer =
        typeof rawAnswer === "string" ? rawAnswer : "";

      const fallbackAnswer =
        results.length > 0
          ? "Here are the most relevant passages found in your documents."
          : "I couldn't find relevant information in the indexed documents.";

      setMessages((current) => [
        ...current,
        {
          id: `${Date.now()}-assistant`,
          role: "assistant",
          question: prompt,
          answer: answer || fallbackAnswer,
          results,
        },
      ]);

      setApiStatus("online");
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: `${Date.now()}-error`,
          role: "assistant",
          question: prompt,
          error: error.message,
          answer: "",
          results: [],
        },
      ]);
    } finally {
      setIsSearching(false);
    }
  }

  function openSource(source) {
    let path = source.fileUrl;

    if (!path && source.documentId) {
      path = ENDPOINTS.pdf.replace(
        "{id}",
        encodeURIComponent(source.documentId)
      );
    }

    if (!path) {
      setNotice(
        "This result does not include a PDF URL or document ID."
      );
      return;
    }

    const url = /^https?:\/\//i.test(path)
      ? new URL(path)
      : new URL(apiUrl(path), window.location.origin);

    if (source.page != null && Number.isFinite(Number(source.page))) {
      url.hash = `page=${Number(source.page)}`;
    }

    window.open(url.toString(), "_blank", "noopener,noreferrer");
  }

  function clearConversation() {
    if (
      messages.length > 0 &&
      !window.confirm("Start a new conversation and clear these messages?")
    ) {
      return;
    }

    setMessages([]);
    setQuestion("");
    setNotice("");
  }

  function handleComposerKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendQuestion();
    }
  }

  return (
    <div className="rag-app">
      <header className="topbar">
        <div className="app-heading">
          <strong>Retrieval-Augmented Generation</strong>
        </div>

        <div className="topbar-actions">

          <button
            className={`icon-button ${settingsOpen ? "active" : ""}`}
            type="button"
            title="Settings"
            aria-label="Settings"
            onClick={() => setSettingsOpen((value) => !value)}
          >
            <Icon name="settings" size={22} />
          </button>
        </div>
      </header>

      <div className="workspace">
        <aside className="sidebar">
          <div className="sidebar-title">
            <div>
              <Icon name="file" size={20} />
              <span>DOCUMENTS</span>
            </div>

            <span className="document-count">{documents.length}</span>
          </div>

          <div className="sidebar-document-list">
            {isLoadingDocuments && documents.length === 0 ? (
              <p className="sidebar-message">Loading documents...</p>
            ) : documents.length === 0 ? (
              <div className="sidebar-empty">
                <Icon name="file" size={25} />
                <p>No documents uploaded yet.</p>
                <small>Upload a PDF to start searching.</small>
              </div>
            ) : (
              documents.map((document) => (
                <article className="sidebar-document" key={document.id ?? document.filename}>
                  <div className="sidebar-pdf-icon">
                    <Icon name="file" size={18} />
                  </div>

                  <div className="sidebar-file-info">
                    <strong title={document.filename}>
                      {document.filename}
                    </strong>

                    <span>
                      {document.pages != null
                        ? `${document.pages} pages`
                        : formatBytes(document.bytes) || document.status}
                    </span>
                  </div>

                  <button
                    className="sidebar-delete"
                    type="button"
                    title={`Delete ${document.filename}`}
                    aria-label={`Delete ${document.filename}`}
                    disabled={!document.id || busy}
                    onClick={() => void deleteDocument(document)}
                  >
                    {deletingId === document.id ? (
                      <span className="tiny-spinner" />
                    ) : (
                      <Icon name="close" size={17} />
                    )}
                  </button>
                </article>
              ))
            )}
          </div>

          {isUploading && (
            <div className="sidebar-upload-progress">
              <div>
                <span>Uploading PDF</span>
                <strong>{uploadProgress}%</strong>
              </div>
              <progress value={uploadProgress} max="100" />
            </div>
          )}

          {notice && (
            <div className="sidebar-notice" role="status">
              <span>{notice}</span>
              <button
                type="button"
                aria-label="Dismiss notice"
                onClick={() => setNotice("")}
              >
                ×
              </button>
            </div>
          )}

          <div className="sidebar-footer">
            <input
              ref={fileInputRef}
              className="hidden-file-input"
              type="file"
              accept=".pdf,application/pdf"
              onChange={(event) => {
                choosePDF(event.target.files?.[0]);
                event.target.value = "";
              }}
              disabled={busy}
            />

            <button
              className="upload-sidebar-button"
              type="button"
              disabled={busy}
              onClick={() => fileInputRef.current?.click()}
            >
              <Icon name="upload" size={18} />
              Upload PDF
            </button>

            <button
              className="refresh-sidebar-button"
              type="button"
              disabled={isLoadingDocuments || busy}
              onClick={() => void loadDocuments()}
            >
              <Icon name="refresh" size={16} />
              Refresh document list
            </button>
          </div>
        </aside>

        <main className="chat-panel">
          {settingsOpen && (
            <section className="settings-popover">
              <div className="settings-heading">
                <strong>Connection settings</strong>
                <button
                  type="button"
                  aria-label="Close settings"
                  onClick={() => setSettingsOpen(false)}
                >
                  ×
                </button>
              </div>

              <p>
                API status: <strong>{apiStatus}</strong>
              </p>
              <p>
                Search endpoint: <code>{ENDPOINTS.search}</code>
              </p>
              <p>
                Documents endpoint: <code>{ENDPOINTS.documents}</code>
              </p>
              <small>
                Configure these values in the frontend .env file.
              </small>
            </section>
          )}

          <div className="chat-scroll">
            {messages.length === 0 ? (
              <div className="welcome-state">
                <div className="welcome-icon">
                  <Icon name="file" size={28} />
                </div>

                <h2>Ask your documents anything.</h2>

                <p>
                  Search your uploaded PDFs and explore the passages
                  that support the results.
                </p>

                <span>
                  Try asking a question in the box below.
                </span>
              </div>
            ) : (
              <div className="conversation">
                {messages.map((message) =>
                  message.role === "user" ? (
                    <div className="user-message-row" key={message.id}>
                      <div className="user-message">
                        {message.content}
                      </div>
                    </div>
                  ) : (
                    <article className="assistant-message" key={message.id}>
                      {message.error ? (
                        <div className="chat-error">
                          <strong>Search failed</strong>
                          <p>{message.error}</p>
                        </div>
                      ) : (
                        <>
                          {message.answer && (
                            <p className="assistant-answer">
                              {message.answer}
                            </p>
                          )}

                          {message.results.map((source, index) => (
                            <section
                              className="source-card"
                              key={`${message.id}-${source.id}-${index}`}
                            >
                              <div className="source-top-line" />

                              <div className="source-meta">
                                <span className="source-filename">
                                  {source.filename}
                                </span>

                                {source.page != null && (
                                  <span>(Page {source.page})</span>
                                )}
                              </div>

                              <div className="score-line">
                                Keyword Match:{" "}
                                <strong>{formatPercent(source.keyword)}</strong>
                              </div>

                              <div className="score-line">
                                Semantic Match:{" "}
                                <strong>{formatPercent(source.semantic)}</strong>
                              </div>

                              <div className="score-line">
                                Final Relevance:{" "}
                                <strong>{formatPercent(source.relevance)}</strong>
                              </div>

                              {source.text && (
                                <p className="source-snippet">
                                  <HighlightText
                                    text={source.text}
                                    question={message.question}
                                  />
                                </p>
                              )}

                              <div className="source-actions">
                                <button
                                  type="button"
                                  className="view-page-button"
                                  onClick={() => openSource(source)}
                                  disabled={source.page == null}
                                >
                                  [ View Page {source.page ?? "—"} ]
                                </button>
                              </div>
                            </section>
                          ))}

                          {message.results.length === 0 && (
                            <div className="no-results">
                              No source passages were returned for this question.
                            </div>
                          )}
                        </>
                      )}
                    </article>
                  )
                )}

                {isSearching && (
                  <div className="searching-indicator">
                    <span className="tiny-spinner" />
                    Searching your documents...
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>
            )}
          </div>

          <div className="composer-area">
            <form className="composer" onSubmit={sendQuestion}>
              <button
                className="composer-attach"
                type="button"
                title="Upload a PDF"
                aria-label="Upload a PDF"
                disabled={busy}
                onClick={() => fileInputRef.current?.click()}
              >
                <Icon name="clip" size={24} />
              </button>

              <textarea
                ref={textareaRef}
                rows={1}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={handleComposerKeyDown}
                placeholder="Ask something..."
                aria-label="Ask a question about your documents"
                disabled={isSearching}
              />

              <button
                className="composer-send"
                type="submit"
                title="Send question"
                aria-label="Send question"
                disabled={!question.trim() || busy}
              >
                <Icon name="send" size={21} />
              </button>
            </form>

            <p className="composer-hint">
              Press Enter to send, Shift + Enter for new line
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}

export default App;