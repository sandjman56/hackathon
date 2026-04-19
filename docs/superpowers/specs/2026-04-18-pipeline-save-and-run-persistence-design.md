# Pipeline Save & Run Persistence Design

**Date:** 2026-04-18  
**Status:** Approved

---

## Problem

After the pipeline completes, there is no way to persist agent outputs. Results live only in frontend memory and are lost on reload. Additionally, gray descriptor text throughout the UI is hard to read.

---

## Goals

1. Explicit "SAVE RESULTS" button appears after pipeline completes
2. One saved run per project; overwriting requires user confirmation with date warning
3. Loading a project from the left bar auto-populates saved pipeline outputs
4. Evaluation scores auto-populate when loading a project with a prior evaluation run
5. "IMPORT RUN" button in EvaluationsView triggers scoring against the saved pipeline run
6. Small gray descriptor text made white throughout the site

---

## Database Schema

### New table: `pipeline_runs`

```sql
CREATE TABLE IF NOT EXISTS pipeline_runs (
  id         SERIAL PRIMARY KEY,
  project_id INTEGER UNIQUE NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  saved_at   TIMESTAMPTZ DEFAULT NOW()
);
```

One row per project. UPSERT on overwrite updates `saved_at`.

### Modified table: `evaluation_scores`

```sql
ALTER TABLE evaluation_scores
  ADD COLUMN IF NOT EXISTS run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE SET NULL;
```

Nullable; populated when evaluation is scored against a saved run.

### Existing agent output tables

No structural changes. `project_id UNIQUE` constraint already enforces one run per project. UPSERT semantics preserved.

### Pipeline auto-save removed

`stream_eia_pipeline()` no longer writes to agent output tables. `project_id` is passed to `/api/run` for RAG scoping only.

---

## Backend API

### New endpoint: `POST /api/projects/{project_id}/save-run`

**Request body:**
```json
{
  "agent_outputs": {
    "project_parser": { ... },
    "environmental_data": { ... },
    "regulatory_screening": { ... },
    "impact_analysis": { ... },
    "report_synthesis": { ... }
  },
  "agent_costs": {
    "project_parser": { "model": "...", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0 },
    ...
  }
}
```

**Query param:** `?force=true` to overwrite an existing run.

**Responses:**
- `200` — `{ "run_id": 1, "saved_at": "2026-04-18T..." }` (new save or forced overwrite)
- `409` — `{ "exists": true, "saved_at": "2026-04-18T..." }` (existing run, force not set)

**Behavior:** UPSERTs into `pipeline_runs` + all 5 agent output tables in a single transaction.

---

### New endpoint: `GET /api/projects/{project_id}/run`

Returns `{ "run_id": 1, "saved_at": "..." }` if a saved run exists, else `{ "run": null }`.  
Used by the frontend to check overwrite state before saving.

---

### Existing endpoint: `GET /api/projects/{project_id}/outputs`

No changes. Returns all 5 agent outputs. Used on project load.

---

### New endpoint: `GET /api/evaluations/scores/{project_id}`

Returns the cached `evaluation_scores` row for this project if it exists, else `null`.  
Used by `EvaluationsView` to auto-populate on project load.

---

## Frontend

### SAVE RESULTS button

- Location: below the pipeline status panel (same column), visible only when pipeline has completed AND a project is selected
- Style: large, full-width green button matching "RUN PIPELINE" aesthetic; label `SAVE RESULTS`
- On click:
  1. Call `GET /api/projects/{project_id}/run`
  2. If no existing run → call `POST /api/projects/{project_id}/save-run`, transition button to `SAVED ✓` for 2s
  3. If existing run → show inline warning below button:  
     `"This project already has saved results from [date]. Save anyway?"` + `CONFIRM OVERWRITE` button
  4. `CONFIRM OVERWRITE` → call `POST /api/projects/{project_id}/save-run?force=true`
- Button shows spinner + disabled state during request

### Project load (left bar LOAD)

- After loading a project, call `GET /api/projects/{project_id}/outputs`
- If outputs exist: populate `ResultsPanel` with saved data; show label `"Loaded from saved run · [date]"` above the output tabs
- If no outputs: `ResultsPanel` remains in "Awaiting pipeline execution..." state

### Evaluations view auto-populate

- On `EvaluationsView` mount with active `project_id`, call `GET /api/evaluations/scores/{project_id}`
- If scores exist, render: overall score, F1, precision, recall, significance accuracy, semantic coverage
- `IMPORT RUN` button: enabled only when loaded project has a saved pipeline run (i.e., `GET /api/projects/{project_id}/run` returns a run)
  - On click: calls `POST /api/evaluations/score` with `{ project_id }`, then refreshes scores display

### Gray text → white

- Audit all components for `color: '#999'`, `color: 'rgba(255,255,255,0.4)'`, `color: 'rgba(255,255,255,0.5)'`, `var(--text-muted)`, and similar low-contrast values
- Replace with `#ffffff` or `rgba(255,255,255,0.85)` to meet readability standard
- Update `--text-muted` CSS custom property in `index.css` as the canonical fix

---

## Error Handling

- Save failure: button reverts to `SAVE RESULTS`, show inline error text
- Load outputs failure: log to console, show no-results state (don't block project load)
- Evaluation score fetch failure: silently show empty state (don't block EvaluationsView)
- `pipeline_runs` UPSERT failure: return 500, frontend shows error

---

## Out of Scope

- Multiple saved runs per project (future)
- Run history / diff view
- Export of saved run as JSON/PDF (already exists as separate feature)
