# Evaluations Tab — Design Spec

## Overview

Add an "Evaluations" tab to the EIA Agent header for uploading and managing existing EIS (Environmental Impact Statement) PDF documents. Bare-bones: upload, list, delete. No processing or ingestion.

## Header Change

- Add an `EVALUATIONS` button to the left of the existing `VIEW DB` button
- Extend the `view` state in `App.jsx` from `'main' | 'db'` to `'main' | 'db' | 'evaluations'`
- Clicking `EVALUATIONS` toggles the view to/from the evaluations page (same pattern as `VIEW DB`)

## Evaluations Page (`EvaluationsView.jsx`)

A full-page view replacing the main layout (same pattern as `DatabaseView`).

**Layout:**
- Top bar: back arrow button, "EVALUATIONS" title, document count
- Upload zone: click-to-upload area accepting PDF files only
- Document list: table with columns — filename, size (human-readable), upload date, delete button

**Upload behavior:**
- Click to select a PDF file (input type="file", accept=".pdf")
- On selection, POST to `/api/evaluations` as multipart form data
- Show the new document in the list on success
- Show error inline on failure

**Delete behavior:**
- Click delete button on a row
- DELETE to `/api/evaluations/{id}`
- Remove from list on success

## Backend Endpoints

Added to `main.py` (matching existing pattern for regulatory sources).

### `GET /api/evaluations`

Returns list of uploaded EIS documents (metadata only, no blob).

Response:
```json
{
  "documents": [
    {
      "id": 1,
      "filename": "example_eis.pdf",
      "size_bytes": 1048576,
      "sha256": "abc123...",
      "uploaded_at": "2026-04-13T12:00:00Z"
    }
  ]
}
```

### `POST /api/evaluations`

Upload a PDF. Multipart form with `file` field. Max 25 MB (same limit as regulatory sources).

Validates: content type is PDF, file starts with `%PDF` magic bytes, non-empty, within size limit.

Returns the created document metadata (201).

### `DELETE /api/evaluations/{id}`

Delete a document by ID. Returns 204 on success, 404 if not found.

## Database Table

```sql
CREATE TABLE IF NOT EXISTS evaluations (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    blob BYTEA NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Created during app lifespan startup (same pattern as other tables).

## New Files

- `frontend/src/components/EvaluationsView.jsx` — evaluations page component

## Modified Files

- `frontend/src/App.jsx` — add evaluations button to header, add view state, render EvaluationsView
- `backend/main.py` — add evaluations table init in lifespan, add 3 endpoints

## Styling

Matches existing dark theme (CSS variables). Same styling patterns as DatabaseView — monospace fonts, green accent, dark cards.
