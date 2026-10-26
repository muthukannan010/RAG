import Icon from "./Icon.jsx";
import { formatBytes } from "../utils/format";

export default function Sidebar({
  documents,
  isLoadingDocuments,
  listError,
  onRefresh,
  onUploadClick,
  onReplaceDocument,
  onDeleteDocument,
  isBusy,
  isUploading,
  uploadProgress,
  deletingId,
  notice,
  onDismissNotice,
}) {
  return (
    <aside className="sidebar">
      <div className="sidebar-title">
        <div>
          <Icon name="file" size={20} />
          <span>DOCUMENTS</span>
        </div>

        <span className="document-count">
          {documents.length}
        </span>
      </div>

      <div className="sidebar-document-list">
        {isLoadingDocuments && documents.length === 0 ? (
          <p className="sidebar-message">
            Loading documents...
          </p>
        ) : listError && documents.length === 0 ? (
          <div className="sidebar-empty" role="alert">
            <Icon name="file" size={24} />
            <p>Unable to load documents.</p>
            <small>{listError}</small>

            <button
              className="refresh-sidebar-button"
              type="button"
              onClick={onRefresh}
            >
              <Icon name="refresh" size={16} />
              Retry
            </button>
          </div>
        ) : documents.length === 0 ? (
          <div className="sidebar-empty">
            <Icon name="file" size={25} />
            <p>No documents uploaded yet.</p>
            <small>
              Upload a PDF to start searching.
            </small>
          </div>
        ) : (
          documents.map((document) => (
            <article
              className="sidebar-document"
              key={document.id ?? document.filename}
            >
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
                    : formatBytes(document.bytes) ||
                      document.status}
                </span>
              </div>

              <div className="sidebar-document-actions">
                <button
                  type="button"
                  className="sidebar-replace"
                  title={`Replace ${document.filename}`}
                  aria-label={`Replace ${document.filename}`}
                  disabled={!document.id || isBusy}
                  onClick={() => onReplaceDocument(document)}
                >
                  <Icon name="replace" size={15} />
                </button>

                <button
                  type="button"
                  className="sidebar-delete"
                  title={`Delete ${document.filename}`}
                  aria-label={`Delete ${document.filename}`}
                  disabled={!document.id || isBusy}
                  onClick={() => onDeleteDocument(document)}
                >
                  {deletingId === document.id ? (
                    <span className="tiny-spinner" />
                  ) : (
                    <Icon name="close" size={16} />
                  )}
                </button>
              </div>
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
        <div className="sidebar-notice" role="status" aria-live="polite">
          <span>{notice}</span>

          <button
            type="button"
            aria-label="Dismiss notice"
            onClick={onDismissNotice}
          >
            ×
          </button>
        </div>
      )}

      <div className="sidebar-footer">
        <button
          className="upload-sidebar-button"
          type="button"
          disabled={isBusy}
          onClick={onUploadClick}
        >
          <Icon name="upload" size={18} />
          Upload PDF
        </button>

        <button
          className="refresh-sidebar-button"
          type="button"
          disabled={isLoadingDocuments || isBusy}
          onClick={onRefresh}
        >
          <Icon name="refresh" size={16} />
          Refresh document list
        </button>
      </div>
    </aside>
  );
}