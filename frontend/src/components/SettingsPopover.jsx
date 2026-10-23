import { API_ENDPOINTS, API_BASE_URL } from "../config/endpoint";

export default function SettingsPopover({
  open,
  onClose,
  apiStatus,
}) {
  if (!open) {
    return null;
  }

  return (
    <section className="settings-popover">
      <div className="settings-heading">
        <strong>Connection settings</strong>

        <button
          type="button"
          aria-label="Close settings"
          onClick={onClose}
        >
          ×
        </button>
      </div>

      <p>
        API status: <strong>{apiStatus}</strong>
      </p>

      <p>
        API base URL:{" "}
        <code>{API_BASE_URL || "Same-origin / Vite proxy"}</code>
      </p>

      <p>
        Search endpoint: <code>{API_ENDPOINTS.search}</code>
      </p>

      <p>
        Documents endpoint:{" "}
        <code>{API_ENDPOINTS.documents}</code>
      </p>

      <small>
        Endpoint values are loaded from the frontend environment
        configuration.
      </small>
    </section>
  );
}