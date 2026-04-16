# Data Model — EIA Agent Database

> Last updated: 2026-04-16. Tables created by `db/vector_store.py:init_db()`.
> Database: `aiagentsdb` (PostgreSQL + pgvector)

---

## projects

Core project records. Each pipeline run is tied to a project.

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `id` | integer | NO | `nextval('projects_id_seq')` |
| `name` | text | NO | |
| `coordinates` | text | NO | |
| `description` | text | YES | |
| `saved_at` | timestamptz | YES | `now()` |

---

## Agent Output Tables

All 5 agent output tables share an identical schema. Each row stores the full JSONB output of one agent for a given project run, along with model/token/cost metadata.

**Shared schema:**

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `id` | integer | NO | `nextval(...)` |
| `project_id` | integer | NO | |
| `output` | jsonb | NO | |
| `model` | text | YES | |
| `input_tokens` | integer | YES | |
| `output_tokens` | integer | YES | |
| `cost_usd` | numeric | YES | |
| `saved_at` | timestamptz | YES | `now()` |

**Tables using this schema:**
- `project_parser_outputs`
- `environmental_data_outputs`
- `regulatory_screening_outputs`
- `impact_analysis_outputs`
- `report_synthesis_outputs`

**Relationships:** `project_id` → `projects.id` (ON DELETE CASCADE)

**Write path:** `pipeline.py:stream_eia_pipeline()` inserts one row per agent after each agent completes, keyed by the optional `project_id` from `POST /api/run`. Rows accumulate across runs; the read endpoint (`GET /api/projects/{id}/outputs`) always returns the most recent row per agent (`ORDER BY saved_at DESC LIMIT 1`).

---

## documents

LlamaIndex pgvector document store.

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `id` | integer | NO | `nextval('documents_id_seq')` |
| `content` | text | YES | |
| `metadata` | jsonb | YES | |
| `embedding` | vector(1536) | YES | |

---

## evaluations

Uploaded EIS PDFs tracked through the ingest pipeline (pending → embedding → ready/failed).

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `id` | integer | NO | `nextval('evaluations_id_seq')` |
| `filename` | text | NO | |
| `sha256` | text | NO | |
| `size_bytes` | integer | NO | |
| `blob` | bytea | NO | |
| `uploaded_at` | timestamptz | NO | `now()` |
| `status` | text | NO | `'pending'` |
| `status_message` | text | YES | |
| `chunks_total` | integer | NO | `0` |
| `chunks_embedded` | integer | NO | `0` |
| `sections_count` | integer | NO | `0` |
| `embedding_dim` | integer | YES | |
| `started_at` | timestamptz | YES | |
| `finished_at` | timestamptz | YES | |

**Status lifecycle:** `pending` → `embedding` → `ready` | `failed`

---

## evaluation_chunks

Parsed + embedded chunks from EIS PDFs. pgvector similarity search scoped per evaluation.

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `id` | uuid | NO | `gen_random_uuid()` |
| `evaluation_id` | integer | NO | |
| `embedding` | vector(N) | YES | |
| `content` | text | NO | |
| `breadcrumb` | text | NO | |
| `chunk_label` | text | NO | |
| `metadata` | jsonb | NO | |
| `created_at` | timestamptz | NO | `now()` |

**Relationships:** `evaluation_id` → `evaluations.id` (CASCADE)

**Metadata JSONB shape:**
```json
{
  "evaluation_id": int,
  "filename": "string",
  "sha256": "string",
  "chapter": "string | null",
  "section_number": "string | null",
  "section_title": "string",
  "breadcrumb": "string",
  "chunk_label": "string",
  "page_start": int,
  "page_end": int,
  "chunk_index": int,
  "total_chunks_in_section": int,
  "token_count": int,
  "has_table": bool
}
```

---

## regulatory_sources

Uploaded regulatory documents (PDFs or eCFR XML). Tracks ingest status and eCFR metadata.

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `id` | uuid | NO | `gen_random_uuid()` |
| `filename` | text | NO | |
| `sha256` | text | NO | |
| `size_bytes` | bigint | NO | |
| `bytes` | bytea | NO | |
| `uploaded_at` | timestamptz | NO | `now()` |
| `status` | text | NO | `'pending'` |
| `status_message` | text | YES | |
| `chunks_total` | integer | YES | |
| `chunks_embedded` | integer | NO | `0` |
| `chunk_count` | integer | NO | `0` |
| `sections_count` | integer | NO | `0` |
| `parser_warnings` | integer | NO | `0` |
| `embedding_dim` | integer | YES | |
| `embedding_started_at` | timestamptz | YES | |
| `embedding_finished_at` | timestamptz | YES | |
| `is_current` | boolean | NO | `false` |
| `source_type` | text | NO | `'pdf_upload'` |
| `content_type` | text | NO | `'application/pdf'` |
| `effective_date` | date | YES | |
| `cfr_title` | integer | YES | |
| `cfr_part` | text | YES | |

---

## regulatory_chunks

Embedded chunks from regulatory sources. pgvector similarity search.

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `id` | uuid | NO | `gen_random_uuid()` |
| `embedding` | vector(N) | YES | |
| `content` | text | NO | |
| `breadcrumb` | text | NO | |
| `metadata` | jsonb | NO | |
| `created_at` | timestamptz | NO | `now()` |
| `source_id` | uuid | YES | |

**Relationships:** `source_id` → `regulatory_sources.id`

---

## regulatory_ingest_log

Audit log for regulatory source ingest operations.

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `id` | bigint | NO | `nextval('regulatory_ingest_log_id_seq')` |
| `ts` | timestamptz | NO | `now()` |
| `correlation_id` | text | NO | |
| `source_id` | uuid | YES | |
| `trigger` | text | NO | |
| `source_type` | text | NO | |
| `cfr_title` | integer | YES | |
| `cfr_part` | text | YES | |
| `effective_date` | date | YES | |
| `status` | text | NO | |
| `duration_ms` | integer | YES | |
| `chunks_count` | integer | YES | |
| `error_message` | text | YES | |
