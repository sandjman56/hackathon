# EIS Evaluation Ingestion

The Evaluations page accepts EIS (Environmental Impact Statement) PDF
uploads. Uploaded PDFs are automatically parsed, chunked, embedded, and
stored in the `evaluation_chunks` table for retrieval.

## Upload flow

```
User uploads PDF → POST /api/evaluations
    → evaluations row (status='pending')
    → BackgroundTask → parse → chunk → embed → upsert
    → evaluations row (status='ready')
```

The Evaluations page polls `/api/evaluations` every 2 seconds while any
row is `pending` or `embedding` and shows:
- Status pill (`PENDING`, `EMBEDDING n/N`, `READY`, `FAILED`)
- Progress bar during `embedding`
- `RETRY` button on `failed` rows
- Filename becomes a clickable link to the chunks inspector when `ready`

## Chunk labels

Every chunk gets a human-readable label:

```
{filename_stem} §{section_number} [p.{page_start}-{page_end}] ({index+1}/{total})
```

Example: `ch-4-environmental-resources §4.2.3 [p.142-143] (2/5)`

Labels are unique per `(evaluation_id, chunk_label)` and back the
upsert's dedupe key.

## API reference

| Method | Path |
|---|---|
| `POST` | `/api/evaluations` — upload PDF, auto-ingest (sha256 dedupe returns existing row) |
| `GET` | `/api/evaluations` — list with status/progress |
| `GET` | `/api/evaluations/{id}` — single row (used by UI polling) |
| `POST` | `/api/evaluations/{id}/reingest` — clears chunks, re-runs pipeline |
| `GET` | `/api/evaluations/{id}/chunks?page=&per_page=` — paginated chunks inspector data |
| `POST` | `/api/evaluations/{id}/search` — scoped similarity search |
| `DELETE` | `/api/evaluations/{id}` — cascades to chunks via FK |

### Search example

```bash
curl -X POST http://localhost:8000/api/evaluations/42/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "groundwater aquifer recharge", "top_k": 5}'
```

## Status lifecycle

- `pending` — row exists, background task queued
- `embedding` — parse complete, embedding chunks (see `chunks_embedded` / `chunks_total`)
- `ready` — all chunks upserted
- `failed` — parse/chunk/embed error; `status_message` has details

On server restart, any row stuck in `pending` or `embedding` is swept to
`failed` with `status_message = 'interrupted by restart'`. Use the
`RETRY` button or `POST /api/evaluations/{id}/reingest` to restart.

## Common failure modes

- **`No sections detected by EIS parser`** — the PDF lacks numbered
  headings the parser recognises (e.g., `1.1`, `4.2.3`). Low-quality
  scans or purely narrative PDFs can trigger this. Currently not
  supported — consider a different document.
- **`Vector dim mismatch`** — logged at startup if the embedding
  provider changed dims between runs. The table is recreated and
  chunks must be re-ingested (use the RETRY button on each row).
- **Status stuck on `embedding` with `0/0`** — the parse step
  produced zero sections. Row will transition to `failed` momentarily
  with a message.

## Database schema

`evaluations` (extended on startup):
- `status TEXT DEFAULT 'pending'`
- `status_message TEXT`
- `chunks_total INTEGER`, `chunks_embedded INTEGER`
- `sections_count INTEGER`, `embedding_dim INTEGER`
- `started_at`, `finished_at TIMESTAMPTZ`

`evaluation_chunks`:
- `id UUID`, `evaluation_id INTEGER REFERENCES evaluations(id) ON DELETE CASCADE`
- `embedding vector(<dim>)`, `content TEXT`, `breadcrumb TEXT`, `chunk_label TEXT`
- `metadata JSONB` — includes `chapter`, `section_number`, `page_start/end`, `token_count`, `has_table`
- Indexes: HNSW on `embedding` (cosine), GIN on `metadata`, UNIQUE `(evaluation_id, chunk_label)`
