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
| POST | /api/v1/documents/{id}/pages/{page}/preview | Render a PDF page and highlight a verified citation |

The API paths must be adjusted to match the actual backend.

## Run and Build

From the frontend directory:

```bash
npm install
npm run dev
# Local RAG Assistant — Semantic Retrieval Backend

## 1. Overview

This backend is the first stage of an on-premises PDF RAG
application. It accepts user-selected PDFs, extracts text,
creates page-aware chunks, generates local embeddings,
persists documents and vectors, and combines semantic and
keyword retrieval to select relevant passages for local LLM
answer generation.

## 2. Architecture

React frontend
    |
    v
FastAPI routes
    |
    v
Document service / Hybrid retrieval service
    |
    +--> PDF extraction and chunking
    |
    +--> Sentence Transformers embeddings
    |
    +--> SQLite document metadata, chunk records and FTS5 index
    |
    +--> Chroma persistent vector index
    |
    v
Weighted RRF results with source metadata

## 3. Technology Choices

- FastAPI: HTTP API and request validation.
- PyMuPDF: PDF text and bounding-box extraction.
- Sentence Transformers: local text embeddings.
- Chroma: persistent vector storage and similarity search.
- SQLite and FTS5: document records, active versions, chunk
  metadata and keyword search.
- pytest: automated tests.

## 4. Project Structure

- app/core: configuration and logging.
- app/api/routes: HTTP API endpoints.
- app/db: SQLite and Chroma persistence.
- app/models: request and response schemas.
- app/services: PDF processing, chunking, embeddings,
  ingestion, document management and retrieval.
- tests: semantic, keyword and hybrid retrieval tests.

## 5. Setup

Use Python 3.11 and install the packages in requirements.txt.

From the backend directory:

    python -m venv .venv
    python -m pip install -r requirements.txt

Copy .env.example to .env and review the configuration.

## 6. Local Model

The Sentence Transformers model is loaded locally:

    sentence-transformers/all-MiniLM-L6-v2

The model may need to download its weights during the
initial setup. For disconnected deployment, stage the model
files before going offline.

## 7. Persistent Storage

- data/documents/: versioned original PDF files.
- data/rag.sqlite3: document records, chunk metadata and the
  synchronized FTS5 keyword index.
- data/chroma/: semantic vector index.

SQLite controls which document versions are active.
Semantic and keyword retrieval filter results to the active
document versions. Startup cleanup attempts to remove inactive
or orphaned vectors, and the FTS5 index is backfilled when first
created.

## 8. Chunking

Initial chunk size: 1,000 characters.
Initial overlap: 150 characters.

Chunks retain their page number and bounding boxes.
These settings are starting values and must be evaluated
with representative PDFs and questions.

## 9. API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | /api/v1/health | API health |
| GET | /api/v1/documents | List documents |
| POST | /api/v1/documents/upload | Upload and index a PDF |
| PUT | /api/v1/documents/{document_id} | Replace a PDF |
| DELETE | /api/v1/documents/{document_id} | Delete a PDF |
| GET | /api/v1/documents/{document_id}/file | Serve the original PDF |
| POST | /api/v1/search | Hybrid retrieval and grounded answer |

## 10. Run the API

From this backend directory:

    python -m uvicorn app.main:app --reload \
        --host 127.0.0.1 --port 8000

API documentation:

    http://127.0.0.1:8000/docs

## 11. Run Tests

    python -m pytest -v

The test suite includes an upload, search, replacement and
deletion flow, plus basic chunking and metadata checks.

The end-to-end test uses deterministic test embeddings to
avoid requiring the real model. It validates the API and
persistence flow, not semantic model quality.

## 12. Current Scope and Limitations

- Hybrid retrieval combines SQLite FTS5 keyword matches and
  Chroma semantic matches using weighted reciprocal rank fusion.
- Local answer generation uses Ollama and cites retrieved sources.
- Image-only scanned PDFs require OCR.
- Bounding boxes currently represent extracted text blocks,
  not necessarily exact chunk-level word boundaries.
- Similarity thresholds and chunking settings need evaluation.
- SQLite, the filesystem and Chroma do not share a single
  atomic transaction; recovery and consistency must be tested.

## 13. Retrieval Configuration

Keyword and semantic candidate counts, final hybrid top-K,
RRF weights and the RRF constant are configurable through the
backend settings. The default keyword and semantic weights are
0.40 and 0.60, respectively.