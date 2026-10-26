## Frontend Architecture

The frontend uses React with a modular structure.
Each module has a specific responsibility to improve
maintainability, testing and debugging.

### Configuration

`src/config/endpoints.js`

Centralizes the API routes, environment settings,
upload limits and document endpoint construction.

### API Client

`src/api/client.js`

Provides shared HTTP request handling, response parsing,
error extraction and connection-failure handling.

### Utilities

- `src/utils/format.js`: formats file sizes, percentages
  and dates.
- `src/utils/normalize.js`: converts backend responses
  into consistent document and search-result objects.
- `src/utils/logger.js`: records frontend errors during
  development without logging complete document contents.

### Components

- `Icon.jsx`: reusable SVG icons.
- `Sidebar.jsx`: document listing, upload, replacement
  and deletion controls.
- `ChatPanel.jsx`: conversation display and question input.
- `SourceCard.jsx`: retrieved source passages and citations.
- `HighlightText.jsx`: highlights query terms in snippets.
- `SettingsPopover.jsx`: shows the configured endpoints
  and API connection status.

### Hooks

- `useDocuments.js`: document retrieval, upload progress,
  replacement, deletion, and operation state.
- `useSearch.js`: search submission, answer messages,
  returned source passages and conversation state.

### Application Entry and Composition

- `main.jsx`: mounts the React application.
- `App.jsx`: combines components and connects hooks.
- `App.css`: styles the layout and responsive interface.

## Error Handling and Logging

The API client handles HTTP errors, connection failures,
and response parsing. Document and search hooks expose
operation state to the UI.

Development logging uses a shared logger. Browser logs
are diagnostics, not a replacement for backend logs.

The FastAPI backend should independently configure logging
and record ingestion, retrieval, indexing and persistence
failures without exposing sensitive document contents.

## API Contract

| Method | Endpoint | Purpose |
|---|---|---|
| GET | /api/v1/health | Check API availability |
| GET | /api/v1/documents | List documents |
| POST | /api/v1/documents/upload | Add PDF |
| PUT | /api/v1/documents/{id} | Replace PDF |
| DELETE | /api/v1/documents/{id} | Delete PDF |
| POST | /api/v1/search | Search documents |
| GET | /api/v1/documents/{id}/file | Open the original PDF |

The API paths must be adjusted to match the actual backend.

## Run and Build

From the frontend directory:

```bash
npm install
npm run dev