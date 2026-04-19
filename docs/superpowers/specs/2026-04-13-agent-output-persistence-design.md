# Agent Output Persistence — Design Spec

**Date:** 2026-04-13
**Status:** Approved

## Problem

After running the EIA pipeline, agent outputs exist only in frontend state. Refreshing the page or navigating away loses all results. Users need the ability to save pipeline outputs and reload them when loading a saved project.

## Decisions

- **One table per agent** (5 tables total) — outputs are structurally different; independent schema evolution per agent
- **Project must be saved first** before outputs can be saved (FK constraint + frontend guard)
- **Multiple runs overwrite** — `UNIQUE (project_id)` with upsert, no run history
- **Store model + cost metadata** alongside each agent's output
- **Loading a saved project auto-loads its outputs** into the UI

## Database Schema

Five tables with identical structure, created in `init_db()` in `backend/db/vector_store.py`:

```sql
CREATE TABLE IF NOT EXISTS project_parser_outputs (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    output JSONB NOT NULL,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd NUMERIC(10,6),
    saved_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (project_id)
);
```

Same structure for: `environmental_data_outputs`, `regulatory_screening_outputs`, `impact_analysis_outputs`, `report_synthesis_outputs`.

- `UNIQUE (project_id)` enables `INSERT ... ON CONFLICT (project_id) DO UPDATE` for overwrite
- `ON DELETE CASCADE` auto-cleans outputs when a project is deleted
- Environmental data agent is non-LLM, so `model`/tokens/cost columns will be NULL

## Backend API

### `POST /api/projects/{project_id}/outputs`

Save all agent outputs for a project.

**Request body:**
```json
{
  "agent_outputs": {
    "project_parser": { "project_type": "solar farm", ... },
    "environmental_data": { "usfws_species": {...}, ... },
    "regulatory_screening": [{ "name": "CWA 404", ... }],
    "impact_analysis": { "actions": [...], "cells": [...] },
    "report_synthesis": { "reports": [...] }
  },
  "agent_costs": {
    "project_parser": { "model": "gemini-2.5-flash", "input_tokens": 120, "output_tokens": 450, "cost_usd": 0.00034 },
    "regulatory_screening": { "model": "claude-haiku-4-5", "input_tokens": 200, "output_tokens": 600, "cost_usd": 0.00051 },
    ...
  }
}
```

**Logic:**
1. Verify project exists — `404` if not, message: "Project not found. Save the project first."
2. For each of the 5 agents with non-null output, upsert into its table
3. All upserts in a single transaction (atomic)
4. Return `200 { "saved": true, "project_id": ... }`

### `GET /api/projects/{project_id}/outputs`

Load all agent outputs for a project.

**Response:**
```json
{
  "agent_outputs": {
    "project_parser": { ... } | null,
    "environmental_data": { ... } | null,
    "regulatory_screening": { ... } | null,
    "impact_analysis": { ... } | null,
    "report_synthesis": { ... } | null
  },
  "agent_costs": {
    "project_parser": { "model": "...", "input_tokens": ..., "output_tokens": ..., "cost_usd": ... } | null,
    ...
  }
}
```

- Returns `200` with all nulls if no outputs exist (not 404 — valid state)
- No changes to `DELETE /api/projects/{project_id}` — `ON DELETE CASCADE` handles cleanup

## Frontend — Save Results Button

**Location:** `App.jsx`, middle column, below `<ResultsPanel>`.

**Visibility conditions:**
- Pipeline not running (`running === false`)
- Agent outputs exist (`Object.keys(agentOutputs).length > 0`)

**Behavior:**
1. Check if current project has an ID (has been saved) — if not, show error flash "Save project first"
2. POST to `/api/projects/{project_id}/outputs` with `agentOutputs` and `agentCosts`
3. On success, flash "SAVED!" (same pattern as existing save button)

**Wiring the project ID:** New `currentProjectId` state in `App.jsx`. `ProjectForm` passes it up via `onProjectIdChange(id)` callback — called with the project ID after save (from POST response) and after load (from loaded project object). Set to `null` when form fields are manually edited (project identity is stale).

## Frontend — Loading Saved Outputs

When user clicks "LOAD" on a saved project in `ProjectForm`:

1. Set form fields (existing behavior)
2. Fetch `GET /api/projects/{project_id}/outputs`
3. If outputs exist: populate `agentOutputs`, `agentCosts`, `results` in App state; set pipeline status to `"complete"` for each agent with output
4. If no outputs: clear pipeline state to idle

**Reconstructing `results`** (used by ResultsPanel) from individual agent outputs:
```js
const reconstructedResults = {
  parsed_project: agentOutputs.project_parser,
  environmental_data: agentOutputs.environmental_data,
  regulations: agentOutputs.regulatory_screening,
  impact_matrix: agentOutputs.impact_analysis,
  report: agentOutputs.report_synthesis,
}
```

## Error Handling

| Scenario | Where | Behavior |
|----------|-------|----------|
| "SAVE RESULTS" clicked, project not saved | Frontend | Error flash "Save project first", no API call |
| Project deleted externally | Backend POST | 404 from FK violation, frontend shows error |
| Partial pipeline (3/5 agents ran) | Frontend | Save what exists, skip agents with no output |
| Load project never run | Backend GET | 200 with all nulls, frontend stays idle |
| Network error | Frontend | Best-effort catch, console log (existing pattern) |
| Environmental data (no LLM) | Backend | model/tokens/cost stored as NULL |

## Files Changed

**Backend:**
- `backend/db/vector_store.py` — add 5 `CREATE TABLE` statements to `init_db()`
- `backend/main.py` — add `POST /api/projects/{project_id}/outputs` and `GET /api/projects/{project_id}/outputs`

**Frontend:**
- `frontend/src/App.jsx` — add `currentProjectId` state, `handleSaveResults`, "SAVE RESULTS" button, pass new callbacks to ProjectForm
- `frontend/src/components/ProjectForm.jsx` — accept `onProjectIdChange` and `onLoadOutputs` callbacks, make `handleLoad` async to fetch outputs
