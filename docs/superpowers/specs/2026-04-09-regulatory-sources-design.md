# Regulatory Sources: DB-backed uploads, live progress, real RAG retrieval

**Date:** 2026-04-09
**Status:** Approved for implementation
**Context:** PR #14 introduced a NEPA ingestion pipeline plus a `View Sources` modal, but (a) the modal only lists on-disk PDFs via a filesystem glob, (b) there is no upload capability, (c) the button is not visible in the Render deploy due to a stale frontend bundle, and (d) `RegulatoryScreeningAgent` is still a stub that returns `[]`. This spec closes all four gaps.

## Goals

1. Store regulatory PDFs in Postgres (single source of truth, survives Render ephemeral disk).
2. Let the user drag-and-drop new PDFs from the `View Sources` modal and see live embedding progress.
3. Replace the filesystem-glob source discovery with a DB-backed registry.
4. Wire `RegulatoryScreeningAgent` to actually query `regulatory_chunks` and return real results.
5. Make sure the `View Sources` button is visible in the deployed Render frontend.

## Non-goals

- **Generic (non-NEPA) PDFs.** The existing parser is hand-tuned for 40 CFR 1500–1508 and similar legal documents. Non-NEPA uploads are rejected with a clear error; a generic parser is a later project.
- **Celery / Redis / external queues.** Background work uses FastAPI `BackgroundTasks`. Good enough for this corpus size.
- **WebSockets / server-sent events for progress.** Frontend polls `GET /sources/{id}` every 2s while anything is embedding.
- **Auth on the sources endpoints.** Matches the rest of this app, which is currently unauthenticated.

## Architecture

```
┌─────────────┐  drop PDF   ┌──────────────────────────┐  parse+chunk+embed   ┌───────────────────┐
│  Frontend   │ ──────────▶ │  POST /regulations/      │ ───────────────────▶ │ regulatory_chunks │
│ SourcesModal│             │  sources (multipart)     │                      │   (pgvector)      │
└──────┬──────┘             └────────────┬─────────────┘                      └─────────▲─────────┘
       │                                 │  insert row                                  │
       │                                 ▼                                              │
       │                    ┌────────────────────────┐                                  │
       │  poll GET /sources │  regulatory_sources    │                                  │
       └───────────────────▶│  (BYTEA, metadata)     │                                  │
                            └────────────────────────┘                                  │
                                                                                        │
┌─────────────────┐  embed query  ┌─────────────────────────┐  top-k search             │
│ Pipeline run    │ ────────────▶ │ RegulatoryScreeningAgent│ ──────────────────────────┘
│ (project state) │               │   (no longer stub)      │
└─────────────────┘               └─────────────────────────┘
```

## Data model

New table `regulatory_sources` (raw psycopg2, new migration in `backend/db/regulatory_sources.py`):

```sql
CREATE TABLE regulatory_sources (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  filename              TEXT        NOT NULL,
  sha256                TEXT        NOT NULL UNIQUE,
  size_bytes            BIGINT      NOT NULL,
  bytes                 BYTEA       NOT NULL,
  uploaded_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  status                TEXT        NOT NULL DEFAULT 'pending',
                        -- 'pending' | 'embedding' | 'ready' | 'failed'
  status_message        TEXT,
  chunks_total          INT,
  chunks_embedded       INT         NOT NULL DEFAULT 0,
  chunk_count           INT         NOT NULL DEFAULT 0,
  sections_count        INT         NOT NULL DEFAULT 0,
  parser_warnings       INT         NOT NULL DEFAULT 0,
  embedding_dim         INT,
  embedding_started_at  TIMESTAMPTZ,
  embedding_finished_at TIMESTAMPTZ,
  is_current            BOOLEAN     NOT NULL DEFAULT FALSE
);

CREATE INDEX regulatory_sources_status_idx ON regulatory_sources (status);
```

Key decisions:

- **`sha256 UNIQUE`** dedupes by content, so re-uploading the same file is idempotent.
- **`status`** is text, not a real enum, to avoid migration pain.
- **`bytes`** lives on the same row as metadata; list queries must exclude it. Repository exposes `list_sources()` (no bytes) and `get_source_bytes(id)` (bytes only).
- **`chunks_total` / `chunks_embedded`** drive the progress bar and ETA. `chunk_count` holds the final count once `status='ready'`.
- **`embedding_started_at`** lets the frontend compute ETA as `(chunks_total - chunks_embedded) / rate`.

### Link to `regulatory_chunks`

No schema change on `regulatory_chunks`. A new field `source_id` is added to the JSONB `metadata`. Delete cascades via:

```sql
DELETE FROM regulatory_chunks WHERE metadata->>'source_id' = $1;
```

The durable key is `source_id`, not `source_file` (which is fragile if filenames are reused).

## API

All endpoints in `backend/main.py`.

```
GET    /api/regulations/sources
       → [{ id, filename, sha256, size_bytes, uploaded_at, status,
            status_message, chunks_total, chunks_embedded, chunk_count,
            sections_count, parser_warnings, embedding_started_at,
            embedding_finished_at, is_current }]
       Excludes BYTEA. Sorted by uploaded_at DESC.

GET    /api/regulations/sources/{id}
       → single row (same fields, no bytes). Used for polling during embedding.

POST   /api/regulations/sources                     (multipart/form-data)
       form: file=<PDF>, is_current=<bool optional, default false>
       1. Validate: Content-Type is application/pdf AND first 4 bytes are %PDF.
          Reject files > 25 MB.
       2. Read bytes, compute sha256.
       3. If sha256 exists → return existing row (200, idempotent re-upload).
       4. Insert row with status='pending'. Return 202 with the created row.
       5. Queue background ingestion via FastAPI BackgroundTasks.

DELETE /api/regulations/sources/{id}
       1. DELETE FROM regulatory_chunks WHERE metadata->>'source_id' = $1
       2. DELETE FROM regulatory_sources WHERE id = $1
       Returns { deleted_chunks: N }
```

**Removed:**

- Old `GET /api/regulations/sources` (filesystem glob) — replaced.
- Old `POST /api/regulations/ingest` (filename-based) — replaced. Ingestion is only triggered by upload.

### Background ingestion task

Runs in `BackgroundTasks` immediately after the upload response is sent:

1. `UPDATE regulatory_sources SET status='embedding', embedding_started_at=NOW() WHERE id=$1`
2. `parse_pdf(bytes_io)` → list of sections. If 0 sections, set `status='failed'`, `status_message='Not a NEPA-style PDF (no CFR sections detected)'`, return.
3. `chunk_sections(sections)` → list of chunks. `UPDATE ... SET chunks_total=N, sections_count=M, parser_warnings=W`.
4. `embed_chunks(chunks, provider, on_progress=...)` — new callback param. The callback bumps `chunks_embedded` via UPDATE, throttled to one write per second OR every 5 chunks, whichever comes first.
5. `upsert_chunks(conn, rows)` — existing function, called with `source_id` in metadata.
6. `UPDATE regulatory_sources SET status='ready', chunk_count=N, embedding_dim=D, embedding_finished_at=NOW()`.
7. On any exception: `UPDATE ... SET status='failed', status_message=str(exc)`. Log the full traceback.

### One-time migration on startup

In the FastAPI `lifespan()`:

```python
if regulatory_sources_is_empty() and (BACKEND_DIR / "NEPA-40CFR1500_1508.pdf").exists():
    # Read file, insert row, kick off ingestion
    auto_import_seed_pdf()
```

Idempotent because of the `sha256 UNIQUE` constraint. Bridges old → new without losing the seed PDF.

## Frontend

Replace `frontend/src/components/SourcesModal.jsx` entirely. Same trigger button on the REGULATORY SCREENING row (PR 14 wiring stays).

### Modal layout

```
┌─────────────────────────────────────────────────────────┐
│ REGULATORY SOURCES                                  ×   │
├─────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────┐ │
│ │     [⇧]   DROP PDF HERE OR CLICK TO BROWSE          │ │
│ │           NEPA-style regulatory documents only      │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│  ● NEPA-40CFR1500_1508.pdf            ✓ READY          │
│    1.8 MB · 247 chunks · 9 sections                    │
│    Uploaded 2026-04-09         [DOWNLOAD] [×]          │
│                                                         │
│  ◐ state-dot-manual.pdf            EMBEDDING…          │
│    3.1 MB · 247 sections detected                      │
│    ▓▓▓▓▓▓▓▓░░░░░░░░░░░  87 / 247 chunks  ~32s         │
│                                                         │
│  ✗ random-doc.pdf                      FAILED          │
│    2.4 MB · Not a NEPA-style PDF (no CFR sections)     │
│                                                   [×]  │
│                                                         │
│  Embedding runs in the background.         [CLOSE]     │
└─────────────────────────────────────────────────────────┘
```

### State machine per row

- `pending` → grey dot, "QUEUED"
- `embedding` → animated dot, progress bar, `chunks_embedded / chunks_total`, ETA
- `ready` → green dot, `chunk_count` + `sections_count` + WARN if `parser_warnings > 0`
- `failed` → red dot, `status_message`, only DELETE allowed

### Progress bar and ETA (client-side)

```js
const elapsed = (now - embedding_started_at) / 1000;       // seconds
const rate = chunks_embedded / elapsed;                    // chunks/sec
const remaining = chunks_total - chunks_embedded;
const etaSecs = rate > 0 ? remaining / rate : null;
// Only render ETA once chunks_embedded >= 5 (smooth startup).
```

Bar fill = `chunks_embedded / chunks_total`, CSS transition for smooth interpolation between polls.

### Polling

While any row is `pending` or `embedding`, `SourcesModal` sets up a 2-second interval that refetches `GET /api/regulations/sources`. Interval clears when no row is in flight. No WebSockets.

### Drag-and-drop

Native HTML5 `onDragOver` / `onDrop`. Hidden `<input type="file" accept="application/pdf" multiple>` for click-to-browse. Multiple files upload sequentially (not parallel) to keep polling simple. Client-side validation: `.pdf` extension, `size <= 25 MB`. Errors surfaced inline above the list.

### Delete

"×" button shows inline confirm ("Delete file and N chunks?"). Calls `DELETE /api/regulations/sources/{id}`, removes the row.

### Re-upload

Same file (by sha256) → server returns existing row. Frontend shows a brief toast "Already uploaded — last embedded {date}." No duplicate row.

## RAG retrieval wiring

Replace the stub in `backend/agents/regulatory_screening.py`.

### New run flow

```
state (parsed_project + environmental_data + coordinates)
   │
   ▼  build_query_text()
query_text (project type + scale + location + flags)
   │
   ▼  embedding_provider.embed()
query_vector
   │
   ▼  search_regulations(conn, vec, top_k=8, filters={"is_current": True})
retrieved: list[{content, breadcrumb, metadata, similarity}]
   │
   ▼  llm.complete(prompt)
raw_json
   │
   ▼  parse + validate
list[Regulation]  → state["regulations"]
```

### Agent changes

- `RegulatoryScreeningAgent.__init__(self, llm, embedding_provider)` — takes both.
- `run()` opens a psycopg2 connection via `_get_connection()`, embeds the query, calls `search_regulations`, formats a prompt with the top 8 snippets, calls `llm.complete`, parses JSON, returns.
- Wired in `backend/pipeline.py` where agents are instantiated. `embedding_provider` is already in `app.state`; pipeline needs to pass it through.

### LLM prompt

```
You are a NEPA compliance assistant. Based on the project below and the
excerpts from the Code of Federal Regulations, return a JSON array of
regulations that apply. Each item:
  { "name": str, "jurisdiction": str, "description": str, "citation": str }

Project:
  type: {type}
  scale: {scale}
  location: {location}
  flags: in_sfha={..}, species_count={..}, wetlands={..}, prime_farmland={..}

Excerpts (top {k} by similarity):
  [1] {breadcrumb} (cite: {citation}, similarity: {s:.2f})
      {content}
  [2] ...

Return only valid JSON. Do not invent citations.
```

### Failure modes

- **Empty corpus** (zero chunks in `regulatory_chunks`): log WARNING, return `[]`. Pipeline does not crash.
- **Zero search hits**: same as empty corpus.
- **DB query exception**: log ERROR with traceback, return `[]`.
- **LLM returns unparseable JSON**: log raw output at DEBUG, return `[]`.

All four paths keep the pipeline running.

## Logging

New logger `eia.rag.regulatory.sources`, same stdout handler pattern as the existing `eia` logger in `backend/main.py`. Every upload gets a request-scoped correlation id (UUID at endpoint entry) that appears in every downstream log line.

### Upload logs

```
[sources:abc123] upload received: filename=state-dot.pdf size=3145728 content_type=application/pdf
[sources:abc123] sha256 computed: 9f3a...  duplicate_of=None
[sources:abc123] inserted source row id=... status=pending
[sources:abc123] background ingest started
[sources:abc123] parse_pdf begin
[sources:abc123] parse_pdf done: 9 sections, 2 warnings in 1.84s
[sources:abc123] chunking begin
[sources:abc123] chunking done: 247 chunks in 0.12s
[sources:abc123] status → embedding  chunks_total=247
[sources:abc123] embedding progress: 5/247 (2.0%) rate=1.2/s eta=202s
[sources:abc123] embedding progress: 50/247 ...
[sources:abc123] upserted 247 chunks into regulatory_chunks in 0.44s
[sources:abc123] status → ready  total_elapsed=63.2s
```

### Retrieval logs (agent)

```
[regulatory:xyz] query_text built: 142 chars
[regulatory:xyz] embedded query in 0.31s  dim=768
[regulatory:xyz] search_regulations: top_k=8 filters={'is_current': True}
[regulatory:xyz] retrieved 8 chunks, similarity range 0.72-0.89
[regulatory:xyz] LLM call begin
[regulatory:xyz] LLM returned 4 regulations in 2.14s
[regulatory:xyz] regulations set, node complete
```

Failures at WARNING/ERROR with the exception, the correlation id, AND written into `regulatory_sources.status_message` so they appear in the modal without trawling Render logs.

## Tests

### Backend — `backend/tests/test_regulatory_sources.py`

1. **DB connection smoke:** `_get_connection()` succeeds; `regulatory_sources` table is created; required columns and indexes exist.
2. **Repository unit tests** (transactional fixture):
   - `insert_source()` dedupes by sha256 on re-insert.
   - `list_sources()` returns rows in descending `uploaded_at` and does NOT include `bytes`.
   - `update_progress(id, embedded, total)` persists counters.
   - `delete_source(id)` cascades: matching `regulatory_chunks` rows are gone.
3. **API tests** (FastAPI `TestClient` with synchronous fake `BackgroundTasks`):
   - `POST /api/regulations/sources` with a small fixture NEPA PDF returns 202 + row; status transitions to `ready` after the fake background task runs.
   - Re-POST same file → returns existing row, no duplicate.
   - POST non-PDF bytes → 400.
   - POST PDF that yields zero sections → row with `status='failed'`, `status_message` mentions "no CFR sections".
   - `GET /api/regulations/sources` response does NOT include a `bytes` field.
   - `GET /api/regulations/sources/{id}` returns progress counters.
   - `DELETE /api/regulations/sources/{id}` returns `deleted_chunks` and removes both rows.
4. **PDF upload end-to-end:** Using the real `NEPA-40CFR1500_1508.pdf`, run upload → parse → chunk → embed (with a stub embedder returning fixed-dim zero vectors for offline runs) → verify chunks land in `regulatory_chunks` with the correct `source_id` in metadata.

### Backend — `backend/tests/test_regulatory_agent.py`

1. Agent with stub embedding provider + seeded `regulatory_chunks` → returns regulations from a fake LLM that echoes canned JSON.
2. Empty corpus → returns `[]`, logs warning, no exception.
3. DB connection failure → returns `[]`, logs error.
4. LLM returns invalid JSON → returns `[]`, logs the raw output.

### Frontend — `frontend/src/components/SourcesModal.test.jsx`

Vitest + `@testing-library/react`:

1. Renders loading state.
2. Renders empty state when API returns `[]`.
3. Renders a ready row with filename, `chunk_count`, DELETE button.
4. Renders an `embedding` row with progress bar (width = `chunks_embedded / chunks_total`) and ETA text.
5. Renders a failed row with red indicator and `status_message`.
6. Drop zone: dropping a PDF calls `fetch` against the upload endpoint with a multipart body.
7. Drop zone: dropping a non-PDF shows an inline error and does NOT call fetch.
8. Clicking DELETE sends a DELETE request and removes the row.
9. Polling: while any row is in `embedding`/`pending`, component sets an interval; test uses fake timers to verify refetch and verifies the interval is cleared when all rows are terminal.

### Frontend — `frontend/src/components/AgentPipeline.test.jsx`

Light regression test:

1. Renders the `VIEW SOURCES` button on the `regulatory_screening` row.
2. Clicking the button opens the modal.
3. Does NOT render the button on any other agent row.

## Deploy verification (mandatory plan step)

The original PR 14 button is not visible in the Render deploy, confirming a stale bundle. After the new PR merges:

1. Watch the Render dashboard build. If the build does not auto-trigger, check `render.yaml` for `autoDeploy: false` and flip or trigger manually.
2. After deploy, hit the live URL with a cache-bust (`?v=<commit-sha>`) to confirm the new bundle is live.
3. Inspect the served `index-*.js` filename in DevTools → Network to confirm it matches the new build hash.
4. Confirm the `VIEW SOURCES` button is visible on the REGULATORY SCREENING row.

This is a checkpoint in the implementation plan, not a "remember to do it."

## Files touched

**Backend — new:**

- `backend/db/regulatory_sources.py` — repository module (table init, insert, list, get_bytes, update_progress, update_status, delete, auto-import)
- `backend/tests/test_regulatory_sources.py`
- `backend/tests/test_regulatory_agent.py`
- `backend/tests/fixtures/` — small NEPA fixture (a single CFR Part trimmed to ~5 sections, hand-crafted PDF or reuse a slice of the real one) + stub embedding provider that returns fixed-dim zero vectors. The end-to-end test uses the real `backend/NEPA-40CFR1500_1508.pdf` to exercise the full ingestion path; unit tests use the slim fixture for speed.

**Backend — changed:**

- `backend/main.py` — replace old `/api/regulations/*` endpoints; add multipart upload; add DELETE; lifespan auto-import
- `backend/rag/regulatory/embedder.py` — add `on_progress` callback to `embed_chunks`
- `backend/rag/regulatory/parser.py` — accept a file-like / bytes input (currently path-only) so we can parse from DB bytes without writing to disk
- `backend/rag/regulatory/store.py` — `build_metadata()` accepts and records `source_id`
- `backend/agents/regulatory_screening.py` — replace stub with real RAG
- `backend/pipeline.py` — pass `embedding_provider` to `RegulatoryScreeningAgent`

**Frontend — new:**

- `frontend/src/components/SourcesModal.test.jsx`
- `frontend/src/components/AgentPipeline.test.jsx`

**Frontend — changed:**

- `frontend/src/components/SourcesModal.jsx` — full rewrite for drag-drop, polling, progress bar, delete

**Docs:**

- `docs/superpowers/specs/2026-04-09-regulatory-sources-design.md` (this file)

## Open risks and mitigations

- **Parser is path-only today.** `parse_pdf(str_path)` in `backend/rag/regulatory/parser.py` uses `pymupdf.open(path)`. PyMuPDF supports `pymupdf.open(stream=bytes, filetype="pdf")` — small, targeted change, covered by existing parser tests.
- **Connection pool exhaustion under rapid uploads.** `_get_connection()` opens a fresh connection per call; background tasks hold one for 30–90s. For the expected workload (one upload at a time from one user) this is fine; flag for follow-up if the app gets multi-user.
- **ETA jumps around early in embedding.** Mitigated by only showing ETA once `chunks_embedded >= 5`.
- **`embed_chunks` progress callback and psycopg2 thread safety.** The callback runs on the asyncio event loop; DB writes from a callback need a fresh connection per write (not the one held open by the background task). Throttled to one write per second so overhead is negligible.
- **Render ephemeral disk vs seed PDF auto-import.** The auto-import reads `backend/NEPA-40CFR1500_1508.pdf` which is in the repo, so it's present on every deploy. The DB row survives across deploys via the unique sha256. First cold start after deploy seeds; subsequent restarts are no-ops.
