# Cost & Latency Tracking — Design Spec
_Date: 2026-04-19_

## Overview

Add per-agent latency tracking to the pipeline, persist all runs to the DB (many runs per project), and expose two new pages — **Cost** and **Latency** — accessible via a dropdown off the EVALUATIONS nav button.

---

## 1. DB Schema Changes

All changes are applied via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in `init_db()` in `backend/db/vector_store.py`. Existing rows receive `NULL` for new columns — safe, no backfill needed.

### `pipeline_runs`
Drop `UNIQUE` constraint on `project_id` (allow many runs per project). Add aggregate columns:

| Column | Type | Notes |
|---|---|---|
| `started_at` | TIMESTAMP | Set when run begins |
| `finished_at` | TIMESTAMP | Set when all agents complete |
| `total_duration_ms` | INTEGER | Sum of all agent durations |
| `total_cost_usd` | FLOAT | Sum of all agent costs |
| `total_input_tokens` | INTEGER | Sum of all agent input tokens |
| `total_output_tokens` | INTEGER | Sum of all agent output tokens |

Existing columns retained: `id`, `project_id`, `saved_at`.

### All 5 agent output tables
(`project_parser_outputs`, `environmental_data_outputs`, `regulatory_screening_outputs`, `impact_analysis_outputs`, `report_synthesis_outputs`)

| Column | Type | Notes |
|---|---|---|
| `run_id` | INTEGER | FK → `pipeline_runs.id`, nullable for legacy rows |
| `duration_ms` | INTEGER | Agent execution time, nullable for legacy rows |

Existing columns retained: `id`, `project_id`, `output`, `model`, `input_tokens`, `output_tokens`, `cost_usd`, `saved_at`.

### Evaluation link
`evaluation_scores` already has `project_id`. Scoring selects the most recent `pipeline_runs` row for that project (by `id DESC`) to source agent outputs.

---

## 2. Pipeline Changes (`backend/pipeline.py`)

### Project save gate
The RUN PIPELINE button in `frontend/src/components/ProjectForm.jsx` is disabled (grayed out, tooltip "Save project first") unless a project is currently saved (i.e. a `project_id` exists in component state). Users must save a project before running the pipeline.

### Run lifecycle
1. **Run start** → `INSERT INTO pipeline_runs (project_id, started_at)` → capture `run_id`
2. **Per agent** → record `start_time = time.time()` before `agent.run(state)`, compute `duration_ms = int((time.time() - start_time) * 1000)` after → store in agent output row alongside existing cost fields, with `run_id`
3. **Run complete** → `UPDATE pipeline_runs SET finished_at=NOW(), total_duration_ms=..., total_cost_usd=..., total_input_tokens=..., total_output_tokens=...`

### SSE event changes
- `agent_complete` event gains `duration_ms` field (already includes cost fields)
- `pipeline_complete` event gains `total_duration_ms` field

---

## 3. Frontend — Pipeline Panel Latency Column

**File:** `frontend/src/components/AgentPipeline.jsx`

Add a latency chip to each agent row, next to the existing cost chip:
- **While agent is running:** live timer counting up in seconds, updated every 100ms via `setInterval`. Format: `Xs.X`
- **On complete:** shows final duration. Format: `Xs.Xs`
- **Before run:** shows `—` (same as cost chip idle state)
- Style: same chip style as cost chip, using `--text-muted` color until complete, then `--green-primary`

---

## 4. Navigation

**File:** `frontend/src/App.jsx` (and navbar component)

EVALUATIONS button becomes a dropdown with three options:
- `PIPELINE EVALS` → existing evaluations view (unchanged)
- `COST` → `MetricsView` rendered with `metric="cost"`
- `LATENCY` → `MetricsView` rendered with `metric="latency"`

Dropdown styled to match existing button aesthetic: dark background, green border/text on hover, monospace font, no external dropdown library.

---

## 5. Cost & Latency Pages

### Shared component: `MetricsView.jsx`
Single component parameterized by `metric` prop: `"cost"` or `"latency"`.

- `metric="cost"` → values in USD (`$X.XXXX`), primary unit label `$`
- `metric="latency"` → values in seconds (`Xs.Xs`), primary unit label `s`

### Layout

#### A. Overview section (aggregated across all runs/projects)

- **Summary stats row:** Total [Cost | Duration], Avg per run, Total run count
- **Bar chart (SVG, no external lib):** X-axis = agent name, Y-axis = avg cost or avg duration across all runs. Bars color-coded by model. Axis labels in `--text-muted`, monospace.
- **Model breakdown table (cost page only):** Model | Input $/1M | Output $/1M | Total tokens used | Total cost

#### B. Run drill-down section

- Project selector dropdown → Run selector dropdown (shows run # + timestamp)
- Per-agent breakdown table: Agent | Model | Input tokens | Output tokens | Cost | Duration
- Totals row at bottom
- Empty state when no project/run selected

### Style
Inline CSS throughout (`styles = {...}` objects), CSS custom properties (`--bg-card`, `--green-primary`, `--text-muted`, `--border`, `--font-mono`). No Tailwind, no CSS files, no new dependencies.

---

## 6. Documentation Updates

After implementation:
- `DATA_MODEL.md` — update `pipeline_runs` schema, update all 5 agent output table schemas
- `docs/eval-pipeline.md` — update API reference for `/api/run`, note run_id in pipeline outputs, document new SSE fields
- `README.md` — add Cost and Latency pages to feature list

---

## Out of Scope

- Exporting cost/latency data (CSV, etc.)
- Per-token breakdown within a single agent call
- Latency tracking for evaluation scoring steps
