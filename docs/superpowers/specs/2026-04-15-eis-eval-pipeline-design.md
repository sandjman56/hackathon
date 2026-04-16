# EIS Evaluation Ingestion Pipeline — Design

**Date:** 2026-04-15
**Branch:** `feat/ecfr-phase-1` (work to continue on a new branch)
**Status:** Design approved

## Goal

Extend the Evaluations page so that when a user uploads an Environmental Impact Statement (EIS) PDF, the backend automatically parses, chunks, embeds, and stores the chunks in a new `evaluation_chunks` table. Expose labeled chunks via a paginated inspector and a scoped similarity-search endpoint.

Samples the parser must handle (EIS-style FEIS chapter PDFs):
- `08_pl-feis_vol-i_ch-4-environmental-resources.pdf`
- `05_pl-feis_vol-i_ch-1-purpose-and-need.pdf`
- `011_pl-feis_vol-i_ch-7-effects.pdf`

## Non-goals

- No changes to the regulatory ingest pipeline. The EIS pipeline is a sibling, not a replacement.
- No agent integration in this phase. The search endpoint is the integration seam; wiring it into an agent is separate work.
- No OCR. EIS source PDFs are text-native. Scanned PDFs are out of scope.
- No chapter/section filtering on the search endpoint in this phase (JSONB filters can be added later when a consumer needs them).

## Architecture

```
Upload PDF → evaluations row (status='pending')
          → BackgroundTasks → _run_evaluation_ingest_background
          → parse_eis_pdf(blob)   → list[RawEisSection]
          → chunk_eis_sections()  → list[EisChunk]   (token-aware, tiktoken)
          → embed_chunks()        → [(breadcrumb, vec), ...]   (reuse rag/regulatory/embedder.py)
          → upsert_evaluation_chunks(conn, rows)
          → evaluations.status='ready'
```

### New modules

- `backend/rag/evaluation/__init__.py`
- `backend/rag/evaluation/parser.py` — pymupdf + font-size heuristic + numbered-heading regex. Emits `RawEisSection(chapter, section_number, section_title, breadcrumb, body, page_start, page_end)`.
- `backend/rag/evaluation/chunker.py` — token-aware splitter. Thresholds match the regulatory chunker: `MIN_TOKENS=200`, `MAX_TOKENS=1500`, `TARGET_TOKENS=700`, `OVERLAP_TOKENS=90`. Splits long sections on paragraph boundaries; short sections kept whole (no sibling-merge — EIS has no CFR-definition-style constraints).
- `backend/rag/evaluation/store.py` — `init_evaluation_chunks_table(conn, embedding_dim)`, `build_eis_metadata()`, `upsert_evaluation_chunks()`, `search_evaluation_chunks(conn, query_embedding, evaluation_id, top_k)`.
- `backend/services/evaluation_ingest.py` — orchestrator. Same shape as `regulatory_ingest.py`: status updates, progress throttling (1s / 5 chunks), error capture.
- `backend/db/evaluations.py` — CRUD helpers for the `evaluations` table (extracted from inline SQL in `main.py`). Adds status/progress updates: `update_evaluation_status`, `update_evaluation_progress`, `mark_stale_as_failed`.

### Shared modules (reuse, no change)

- `backend/rag/regulatory/embedder.py` — provider-agnostic, already exposes `embed_chunks(chunks, provider, concurrency, on_progress)` and `detect_embedding_dimension(provider)`. Takes any object exposing a `.body` attribute, so `EisChunk` works without glue.
- `backend/llm/provider_factory.py` — existing embedding provider.

### Startup lifespan additions (in `backend/main.py`)

1. `init_evaluation_chunks_table(_conn, embedding_dim=dim)` — runs after the existing `regulatory_chunks` init, uses the same detected dimension.
2. `ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS ...` for: `status`, `status_message`, `chunks_total`, `chunks_embedded`, `sections_count`, `embedding_dim`, `started_at`, `finished_at`.
3. Sweep stuck rows: `UPDATE evaluations SET status='failed', status_message='interrupted by restart' WHERE status IN ('pending','embedding')`.

## Database schema

### `evaluations` (extend existing)

```sql
ALTER TABLE evaluations
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS status_message TEXT,
  ADD COLUMN IF NOT EXISTS chunks_total INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS chunks_embedded INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS sections_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS embedding_dim INTEGER,
  ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ;
```

`id` stays `SERIAL` (existing rows use it; no need to migrate to UUID). Valid `status` values: `pending`, `embedding`, `ready`, `failed`.

### `evaluation_chunks` (new)

```sql
CREATE TABLE IF NOT EXISTS evaluation_chunks (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    evaluation_id  INTEGER NOT NULL
                   REFERENCES evaluations(id) ON DELETE CASCADE,
    embedding      vector(<dim>),
    content        TEXT NOT NULL,
    breadcrumb     TEXT NOT NULL,
    chunk_label    TEXT NOT NULL,
    metadata       JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS evaluation_chunks_dedupe
  ON evaluation_chunks (evaluation_id, chunk_label);
CREATE INDEX IF NOT EXISTS evaluation_chunks_eval_id_idx
  ON evaluation_chunks (evaluation_id);
CREATE INDEX IF NOT EXISTS evaluation_chunks_metadata_gin
  ON evaluation_chunks USING GIN (metadata jsonb_path_ops);
CREATE INDEX IF NOT EXISTS evaluation_chunks_embedding_hnsw
  ON evaluation_chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m=16, ef_construction=64);
```

If a dimension mismatch is detected at startup (existing column dim ≠ provider dim), the init function logs and recreates the table — same pattern as `init_regulatory_table`.

### Chunk label format

`chunk_label` is a human-readable, stable per-evaluation key used for dedupe, UI display, and retrieval filtering. Format:

```
{filename_stem} §{section_number} [p.{page_start}-{page_end}] ({chunk_index+1}/{total_chunks_in_section})
```

Example: `ch-4-environmental-resources §4.2.3 [p.142-143] (2/5)`

For front-matter or non-numbered content that lacks a section number, use the chapter/section title in place of the number: `ch-1-purpose-and-need §intro [p.1-2] (1/1)`.

### Chunk metadata JSONB

Per chunk:
- `evaluation_id` (int, also in FK column)
- `filename`, `sha256` (from parent evaluation row)
- `chapter` (string, e.g. `"4"`, or `null` for front-matter)
- `section_number` (string, e.g. `"4.2.3"`, or `null`)
- `section_title` (string)
- `breadcrumb` (string — full heading hierarchy joined with ` > `)
- `chunk_label` (string — same as column, denormalized for convenience)
- `page_start`, `page_end` (ints)
- `chunk_index`, `total_chunks_in_section` (ints)
- `token_count` (int)
- `has_table` (bool — heuristic from chunker)

## API surface

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/evaluations` | **Extended.** Sets `status='pending'`, enqueues background ingest. Returns row including new status fields. |
| `GET` | `/api/evaluations` | **Extended.** Returns new status/progress columns. |
| `GET` | `/api/evaluations/{id}` | **New.** Single-row fetch used by the polling UI. |
| `POST` | `/api/evaluations/{id}/reingest` | **New.** Deletes existing chunks, resets counters, re-runs background ingest. Powers the `RETRY` button. |
| `GET` | `/api/evaluations/{id}/chunks?page=&per_page=` | **New.** Paginated chunks sorted by `(chapter, section_number, chunk_index)`. `per_page` capped at 200. Returns `chunk_label`, `breadcrumb`, `content`, `metadata`, `page_start`, `page_end`. |
| `POST` | `/api/evaluations/{id}/search` | **New.** Body `{"query": str, "top_k": int (default 5, max 50)}`. Embeds the query, runs cosine similarity scoped to the evaluation, returns `[{"chunk_label","breadcrumb","content","metadata","similarity"}, ...]`. |
| `DELETE` | `/api/evaluations/{id}` | **Existing.** `ON DELETE CASCADE` on the FK handles chunk cleanup. |

### Re-ingest behavior

- `POST /api/evaluations` with a duplicate `sha256`: returns the existing row. Does **not** re-ingest. If status is `failed`, caller uses the reingest endpoint.
- `POST /api/evaluations/{id}/reingest`: deletes existing chunks for that evaluation, resets `chunks_total`, `chunks_embedded`, `status_message`, sets `status='pending'`, enqueues the background task. 409 if currently `status='embedding'`.

### Background task

`_run_evaluation_ingest_background(eval_id, cid)` mirrors `_run_ingest_background` and `_run_ecfr_ingest_background`: opens its own DB connection, calls the orchestrator, logs exceptions with traceback, never re-raises (FastAPI `BackgroundTasks` swallows them otherwise).

## Parser design

Input: raw PDF bytes. Output: `list[RawEisSection]`.

1. Open with `pymupdf.open(stream=blob, filetype="pdf")`.
2. For each page, extract text blocks with font metadata (`page.get_text("dict")`).
3. Derive body-text font size (modal font size across the doc).
4. A block is a **heading candidate** if: font size > 1.15 × body, OR bold weight, AND matches the numbered-heading regex: `^(\d+(?:\.\d+){0,3})\s+(.+)$`.
5. Also detect chapter titles: blocks matching `^Chapter\s+(\d+)` or `^(\d+)\.\s+[A-Z]` on a page with fewer than 3 body blocks.
6. Walk page-ordered blocks, maintaining a 4-level heading stack. Each heading closes the prior section; the new section collects body text until the next heading.
7. `RawEisSection` carries: `chapter` (derived from first segment of `section_number`), `section_number`, `section_title`, `breadcrumb` (joined stack), `body`, `page_start`, `page_end`, `has_table_hint` (if any block on the pages looks table-like).

**Fallbacks:**
- Heading regex fails entirely → fall back to page-group sections (one `RawEisSection` per 2–3 pages). Logged as a warning.
- Empty body → section skipped.
- No detected chapters → `chapter=None`, `breadcrumb` uses section number only.

Parser warnings are counted and surfaced in `status_message` on `ready` if non-zero (non-fatal), mirroring the regulatory pattern.

## Chunker design

Input: `list[RawEisSection]`. Output: `list[EisChunk]`.

- Each chunk is one RawEisSection by default.
- Sections > `MAX_TOKENS` split on paragraph boundaries (blank-line split). If any slice still exceeds `MAX_TOKENS`, hard-split on token count with `OVERLAP_TOKENS` overlap between slices (same algorithm as regulatory chunker).
- Sections < `MIN_TOKENS` are kept whole. No sibling merging (EIS has no definitions-style constraint that justifies it).
- `has_table` flag carries from `has_table_hint` OR a markdown-pipe regex match on the chunk body.
- `chunk_index` is 0-based within the section; `total_chunks_in_section` is the slice count.
- Token counting uses the existing `tiktoken.get_encoding("cl100k_base")` encoder — share with regulatory chunker via a tiny `rag/_tokens.py` helper (extract `count_tokens` to avoid circular imports and keep both chunkers thin).

## Frontend design

### `EvaluationsView.jsx` (extend existing)

- Add status pill per row: `PENDING` / `EMBEDDING 42/120` / `READY` / `FAILED` — colors mirror `SourcesModal`.
- Progress bar under the pill when `status='embedding'`, width `chunks_embedded / chunks_total`.
- Tooltip on failed pill shows `status_message`.
- `RETRY` button visible only when `status='failed'`; calls `POST /api/evaluations/{id}/reingest`.
- Row click navigates to `EvaluationChunksView` (via App state, same pattern as `TableDetail` → `ChunksView`).
- Polling: `setInterval` at 2s while any row has `status ∈ {'pending','embedding'}`. Cancel on unmount. Guard setState after unmount using the `pollOnce` pattern from commit `bf6f232`.

### `EvaluationChunksView.jsx` (new)

- Mirrors `ChunksView.jsx` in layout/structure.
- Two view modes via top-bar toggle:
  - **CHUNKS** (default) — scrollable paginated list of collapsible rows. Each row shows chunk label, breadcrumb, page range. PREVIEW button expands full content in a styled `<pre>` block.
  - **FULL TABLE** — traditional table with LABEL, BREADCRUMB, PAGES, and expandable CONTENT columns.
- Paginated list (25 per page default) sorted by natural section order. Pagination shows numbered page buttons with ellipsis.
- Switching modes clears expanded state.
- Back button returns to `EvaluationsView`.
- Error and loading states match `ChunksView` (race/err/a11y hardening from commit `997c71c`).

### `App.jsx`

- Add `view='evaluation-chunks'` with `selectedEvaluationId` state.
- Route: `EvaluationsView → onOpenChunks(evalId) → setView('evaluation-chunks')`.

## Testing

### Backend (pytest)

- `tests/test_eis_parser.py` — real sample PDFs (`ch-1-purpose-and-need.pdf`, one other). Assert: section count > 0, hierarchy depth correct, unique breadcrumbs, page ranges non-decreasing. Mark slow; copy a small sample into `tests/fixtures/eis/` (a truncated version if size is an issue) to keep CI fast.
- `tests/test_eis_chunker.py` — pure-function: MIN/MAX enforcement, paragraph-split priority over token-split, chunk_label uniqueness, has_table propagation.
- `tests/test_evaluation_store.py` — init DDL idempotent, dim-mismatch drop/recreate, upsert de-dupes on `(evaluation_id, chunk_label)`, FK cascade deletes chunks when parent row deleted, search scopes by `evaluation_id`.
- `tests/test_evaluation_ingest.py` — end-to-end with a tiny fixture PDF + stub embedding provider (fixed-dim vectors, same pattern as `test_regulatory_ingest.py`). Asserts status transitions, `chunks_embedded` monotonic, final rowcount.
- `tests/test_evaluations_api.py` — POST upload, GET poll, POST search, GET chunks list with pagination, POST reingest, DELETE cascade.
- `tests/test_evaluation_startup_sweep.py` — insert stuck row, call sweep, assert `status='failed'` and `status_message` set.

### Frontend (Vitest)

- `EvaluationsView.test.jsx` — polling starts only with non-terminal rows, stops on unmount, progress bar renders, RETRY appears on failed.
- `EvaluationChunksView.test.jsx` — pagination, breadcrumb rendering, back button, loading/error states, mode toggle, expanded state reset on mode switch.

## Documentation updates

- New `docs/eval-pipeline.md` — operator guide mirroring `docs/ingest-ecfr.md`. Covers: upload flow, status lifecycle, retry, chunks inspector, search endpoint, common failure modes.
- `README.md` — add "EIS Evaluation Ingestion" subsection under the existing "Regulatory Source Ingestion" section, pointing at the new doc.

## Risks and open questions

- **Heading detection fragility:** EIS PDFs from different authoring tools vary. The parser has a page-group fallback, but the fallback produces low-quality breadcrumbs. Mitigation: log warnings, surface parser_warnings count in status_message. Accept as known limitation.
- **Embedding cost for large EIS:** a full FEIS chapter can be 50–150 pages, producing 200–500 chunks. One upload can be a non-trivial embedding call (OpenAI: ~$0.01–0.05). The user is uploading intentionally; no throttling in this phase.
- **Binary blob size:** `evaluations.blob` already caps at 25 MB. FEIS chapters are typically 5–20 MB. No change needed.
- **Concurrency:** BackgroundTasks is single-process. Multiple simultaneous uploads serialize on the embedding provider's internal concurrency (default 4). Acceptable for current usage.
