# Data Model — EIA Agent Database

> Last updated: 2026-04-19. Tables created by `db/vector_store.py:init_db()`.
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
| `run_id` | integer | YES | FK → `pipeline_runs.id` |
| `output` | jsonb | NO | |
| `model` | text | YES | |
| `input_tokens` | integer | YES | |
| `output_tokens` | integer | YES | |
| `cost_usd` | numeric | YES | |
| `duration_ms` | integer | YES | |
| `saved_at` | timestamptz | YES | `now()` |

**Tables using this schema:**
- `project_parser_outputs`
- `environmental_data_outputs`
- `regulatory_screening_outputs`
- `impact_analysis_outputs`
- `report_synthesis_outputs`

**Relationships:** `project_id` → `projects.id` (ON DELETE CASCADE); `run_id` → `pipeline_runs.id` (nullable)

**Write path:** `POST /api/projects/{id}/save-run` inserts one row per agent per run. Multiple runs per project are stored. The read endpoint (`GET /api/projects/{id}/outputs`) returns the most recent row per agent (`ORDER BY run_id DESC NULLS LAST, saved_at DESC LIMIT 1`).

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
| `project_id` | integer | YES | FK → `projects.id` ON DELETE SET NULL |

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
| `project_id` | integer | YES | FK → `projects.id` ON DELETE SET NULL |

**Relationships:** `project_id` → `projects.id` (ON DELETE SET NULL). One source belongs to at most one project. When a project is deleted its sources become unassigned (not deleted).

**Write path:** Set via `PATCH /api/regulations/sources/assign` (`assign_sources_to_project` in `db/regulatory_sources.py`). During pipeline execution, `RegulatoryScreeningAgent` queries source IDs for the run's `project_id` and restricts RAG retrieval to those sources only. Falls back to all sources if none are assigned to the project.

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

## evaluation_ground_truth

LLM-extracted ground truth cache per EIS document. Populated on first `POST /api/evaluations/score`; reused on subsequent calls for the same document.

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `id` | integer | NO | `nextval(...)` |
| `evaluation_id` | integer | NO | |
| `extracted_at` | timestamptz | NO | `now()` |
| `llm_model` | text | YES | |
| `categories` | jsonb | NO | |

**Relationships:** `evaluation_id` → `evaluations.id` (CASCADE). UNIQUE on `evaluation_id`.

**`categories` JSONB shape** (array of objects):
```json
[
  {
    "category_name": "wetlands",
    "significance": "significant",
    "mitigation": ["compensatory"],
    "evidence": "The Preferred Alternative would disturb 8.01 acres of wetlands."
  }
]
```

**Write path:** `rag_eval/extractor.py:extract_ground_truth()` → `db/evaluation_scores.py:upsert_ground_truth()` on first scoring request. Subsequent requests read cached value without calling LLM.

---

## pipeline_runs

One row per pipeline run per project. Multiple runs per project are allowed. Created each time the user clicks SAVE RESULTS. Provides a stable `run_id` anchor for evaluation scoring and the metrics pages.

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `id` | integer | NO | `nextval(...)` |
| `project_id` | integer | NO | FK → `projects.id` (CASCADE) |
| `started_at` | timestamptz | YES | |
| `finished_at` | timestamptz | YES | `now()` at save time |
| `total_duration_ms` | integer | YES | sum of all agent `duration_ms` |
| `total_cost_usd` | numeric(10,6) | YES | sum of all agent `cost_usd` |
| `total_input_tokens` | integer | YES | sum of all agent `input_tokens` |
| `total_output_tokens` | integer | YES | sum of all agent `output_tokens` |
| `saved_at` | timestamptz | YES | `now()` |

**Write path:** `POST /api/projects/{id}/save-run` — always INSERTs a new row + all 5 agent output rows atomically. Returns `{"run_id": int, "saved_at": "..."}`.

**Read path:** `GET /api/projects/{id}/run` — returns the most recent `{run_id, saved_at}` or `{run: null}`.

**Metrics paths:** `GET /api/metrics/overview`, `GET /api/metrics/runs`, `GET /api/metrics/runs/{run_id}` — aggregate and drill-down queries across all runs.

---

## evaluation_scores

One evaluation score per project, aggregated across all EIS documents linked to that project. Written by `POST /api/evaluations/score`, read by `GET /api/evaluations/score/{project_id}`.

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `id` | integer | NO | `nextval(...)` |
| `project_id` | integer | NO | FK → `projects.id` (CASCADE) |
| `evaluation_id` | integer | YES | legacy FK → `evaluations.id` (SET NULL) |
| `run_id` | integer | YES | FK → `pipeline_runs.id` (SET NULL) — future use, currently always NULL |
| `scored_at` | timestamptz | NO | `now()` |
| `category_f1` | numeric(6,4) | YES | |
| `category_precision` | numeric(6,4) | YES | |
| `category_recall` | numeric(6,4) | YES | |
| `significance_accuracy` | numeric(6,4) | YES | |
| `semantic_coverage` | numeric(6,4) | YES | |
| `overall_score` | numeric(6,4) | YES | |
| `detail` | jsonb | NO | `{}` |

**Relationships:** `project_id` → `projects.id` (CASCADE). UNIQUE on `project_id` — re-scoring a project overwrites its previous result via UPSERT. Ground truth is merged from all `evaluations` rows where `project_id` matches and `status = 'ready'`.

**`detail` JSONB shape:**
```json
{
  "per_category": {
    "wetlands": {"label": "TP", "agent_significance": "significant", "gt_significance": "significant", "gt_matched_name": "wetlands", "gt_evidence": "..."},
    "air_quality": {"label": "FN", "agent_significance": "none", "gt_significance": "minimal", ...}
  },
  "tp": ["wetlands", "environmental_justice"],
  "fp": [],
  "fn": ["air_quality"],
  "significance_samples": 7,
  "scope_note": "F1 computed over the 8 agent-designed categories only."
}
```

**Scoring weights:** Category F1 × 0.40 + Significance Accuracy × 0.40 + Semantic Coverage × 0.20.

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
