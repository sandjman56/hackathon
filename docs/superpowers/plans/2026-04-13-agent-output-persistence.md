# Agent Output Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save and load per-agent pipeline outputs linked to saved projects, with a "SAVE RESULTS" button and auto-load on project load.

**Architecture:** 5 new PostgreSQL tables (one per agent) with JSONB output + model/cost metadata, created at startup in `init_db()`. Two new API endpoints for save/load. Frontend gets a `currentProjectId` state, a save results button below the output panel, and async load that fetches outputs.

**Tech Stack:** PostgreSQL (psycopg2), FastAPI, React

**Spec:** `docs/superpowers/specs/2026-04-13-agent-output-persistence-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/db/vector_store.py` | Add 5 `CREATE TABLE` statements to `init_db()` |
| Modify | `backend/main.py` | Add Pydantic models + `POST`/`GET` `/api/projects/{id}/outputs` endpoints |
| Create | `backend/tests/test_agent_outputs_api.py` | API integration tests for save/load endpoints |
| Modify | `frontend/src/App.jsx` | Add `currentProjectId` state, `handleSaveResults()`, save results button, wire callbacks |
| Modify | `frontend/src/components/ProjectForm.jsx` | Accept `onProjectIdChange`/`onLoadOutputs` callbacks, make `handleLoad` async |

---

### Task 1: Add agent output tables to `init_db()`

**Files:**
- Modify: `backend/db/vector_store.py:20-52`

- [ ] **Step 1: Add 5 CREATE TABLE statements to `init_db()`**

In `backend/db/vector_store.py`, add the following after the `projects` table creation (after line 42, before `conn.commit()`):

```python
        # Agent output tables — one per pipeline agent
        for table_name in (
            "project_parser_outputs",
            "environmental_data_outputs",
            "regulatory_screening_outputs",
            "impact_analysis_outputs",
            "report_synthesis_outputs",
        ):
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
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
            """)
```

- [ ] **Step 2: Verify tables are created on startup**

Run the backend server to confirm no errors:

```bash
cd backend && python -c "from db.vector_store import init_db; init_db(); print('OK')"
```

Expected: `OK` with no errors. Tables appear in the database.

- [ ] **Step 3: Commit**

```bash
git add backend/db/vector_store.py
git commit -m "feat(db): add 5 agent output tables to init_db()"
```

---

### Task 2: Add POST endpoint to save agent outputs

**Files:**
- Modify: `backend/main.py:222-269`
- Test: `backend/tests/test_agent_outputs_api.py` (create)

- [ ] **Step 1: Write failing test for save endpoint**

Create `backend/tests/test_agent_outputs_api.py`:

```python
"""API tests for /api/projects/{id}/outputs endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(stub_embedder, monkeypatch):
    import main
    monkeypatch.setattr(main, "get_embedding_provider", lambda: stub_embedder)
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def saved_project(client):
    """Create a project and return its data."""
    r = client.post("/api/projects", json={
        "name": "Test Solar Farm",
        "coordinates": "40.4406, -79.9959",
        "description": "A 5 MW solar installation",
    })
    assert r.status_code == 201
    return r.json()


SAMPLE_OUTPUTS = {
    "agent_outputs": {
        "project_parser": {"project_type": "solar farm", "scale": "5 MW"},
        "environmental_data": {"usfws_species": {"count": 0}},
        "regulatory_screening": [{"name": "CWA 404", "jurisdiction": "Federal"}],
        "impact_analysis": {"actions": ["clearing"], "cells": []},
        "report_synthesis": {"reports": [{"document_type": "EA", "sections": []}]},
    },
    "agent_costs": {
        "project_parser": {
            "model": "gemini-2.5-flash",
            "input_tokens": 120,
            "output_tokens": 450,
            "cost_usd": 0.00034,
        },
        "environmental_data": None,
        "regulatory_screening": {
            "model": "claude-haiku-4-5",
            "input_tokens": 200,
            "output_tokens": 600,
            "cost_usd": 0.00051,
        },
        "impact_analysis": {
            "model": "gemini-2.5-flash",
            "input_tokens": 500,
            "output_tokens": 1200,
            "cost_usd": 0.0012,
        },
        "report_synthesis": {
            "model": "gemini-2.5-flash",
            "input_tokens": 800,
            "output_tokens": 2000,
            "cost_usd": 0.002,
        },
    },
}


def test_save_outputs_success(client, saved_project):
    r = client.post(
        f"/api/projects/{saved_project['id']}/outputs",
        json=SAMPLE_OUTPUTS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is True
    assert body["project_id"] == saved_project["id"]


def test_save_outputs_project_not_found(client):
    r = client.post("/api/projects/99999/outputs", json=SAMPLE_OUTPUTS)
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_save_outputs_overwrites(client, saved_project):
    """Second save for the same project overwrites the first."""
    pid = saved_project["id"]
    client.post(f"/api/projects/{pid}/outputs", json=SAMPLE_OUTPUTS)

    updated = {
        "agent_outputs": {
            **SAMPLE_OUTPUTS["agent_outputs"],
            "project_parser": {"project_type": "wind farm", "scale": "10 MW"},
        },
        "agent_costs": SAMPLE_OUTPUTS["agent_costs"],
    }
    r = client.post(f"/api/projects/{pid}/outputs", json=updated)
    assert r.status_code == 200

    # Load and verify overwrite
    r2 = client.get(f"/api/projects/{pid}/outputs")
    assert r2.json()["agent_outputs"]["project_parser"]["project_type"] == "wind farm"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_agent_outputs_api.py -v
```

Expected: FAIL — endpoints don't exist yet (404 from FastAPI).

- [ ] **Step 3: Add Pydantic model and POST endpoint to main.py**

In `backend/main.py`, add the following after the `SaveProjectRequest` class (line 226) and before the `list_projects` endpoint (line 229):

```python
AGENT_OUTPUT_TABLES = {
    "project_parser": "project_parser_outputs",
    "environmental_data": "environmental_data_outputs",
    "regulatory_screening": "regulatory_screening_outputs",
    "impact_analysis": "impact_analysis_outputs",
    "report_synthesis": "report_synthesis_outputs",
}


class SaveOutputsRequest(BaseModel):
    agent_outputs: dict
    agent_costs: dict = Field(default_factory=dict)
```

Then add the POST endpoint after the `delete_project` endpoint (after line 263):

```python
@app.post("/api/projects/{project_id}/outputs")
def save_project_outputs(project_id: int, req: SaveOutputsRequest):
    conn = _get_connection()
    try:
        cur = conn.cursor()
        # Verify project exists
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Project not found. Save the project first.")

        for agent_key, table_name in AGENT_OUTPUT_TABLES.items():
            output = req.agent_outputs.get(agent_key)
            if output is None:
                continue
            cost = req.agent_costs.get(agent_key) or {}
            cur.execute(
                f"""
                INSERT INTO {table_name} (project_id, output, model, input_tokens, output_tokens, cost_usd)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id) DO UPDATE SET
                    output = EXCLUDED.output,
                    model = EXCLUDED.model,
                    input_tokens = EXCLUDED.input_tokens,
                    output_tokens = EXCLUDED.output_tokens,
                    cost_usd = EXCLUDED.cost_usd,
                    saved_at = NOW()
                """,
                (
                    project_id,
                    psycopg2.extras.Json(output),
                    cost.get("model"),
                    cost.get("input_tokens"),
                    cost.get("output_tokens"),
                    cost.get("cost_usd"),
                ),
            )
        conn.commit()
        return {"saved": True, "project_id": project_id}
    finally:
        cur.close()
        conn.close()
```

Also add the import at the top of `main.py` (with the other psycopg2 imports):

```python
import psycopg2.extras
```

- [ ] **Step 4: Run tests to verify save tests pass**

```bash
cd backend && python -m pytest tests/test_agent_outputs_api.py::test_save_outputs_success tests/test_agent_outputs_api.py::test_save_outputs_project_not_found -v
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_agent_outputs_api.py
git commit -m "feat(api): add POST /api/projects/{id}/outputs endpoint"
```

---

### Task 3: Add GET endpoint to load agent outputs

**Files:**
- Modify: `backend/main.py` (add endpoint after POST)
- Modify: `backend/tests/test_agent_outputs_api.py` (add load tests)

- [ ] **Step 1: Write failing tests for load endpoint**

Append to `backend/tests/test_agent_outputs_api.py`:

```python
def test_load_outputs_after_save(client, saved_project):
    pid = saved_project["id"]
    client.post(f"/api/projects/{pid}/outputs", json=SAMPLE_OUTPUTS)

    r = client.get(f"/api/projects/{pid}/outputs")
    assert r.status_code == 200
    body = r.json()

    # agent_outputs round-trip
    assert body["agent_outputs"]["project_parser"]["project_type"] == "solar farm"
    assert body["agent_outputs"]["regulatory_screening"][0]["name"] == "CWA 404"
    assert body["agent_outputs"]["report_synthesis"]["reports"][0]["document_type"] == "EA"

    # agent_costs round-trip
    pp_cost = body["agent_costs"]["project_parser"]
    assert pp_cost["model"] == "gemini-2.5-flash"
    assert pp_cost["input_tokens"] == 120
    assert pp_cost["output_tokens"] == 450
    assert float(pp_cost["cost_usd"]) == pytest.approx(0.00034, abs=1e-6)

    # environmental_data has no cost
    assert body["agent_costs"]["environmental_data"] is None


def test_load_outputs_no_outputs(client, saved_project):
    """Loading outputs for a project that hasn't been run returns all nulls."""
    r = client.get(f"/api/projects/{saved_project['id']}/outputs")
    assert r.status_code == 200
    body = r.json()
    for agent in AGENT_NAMES:
        assert body["agent_outputs"][agent] is None
        assert body["agent_costs"][agent] is None


def test_load_outputs_project_not_found(client):
    r = client.get("/api/projects/99999/outputs")
    assert r.status_code == 404
```

Note: the test file uses `AGENT_NAMES` — add this constant at the top of the test file alongside `SAMPLE_OUTPUTS`:

```python
AGENT_NAMES = [
    "project_parser", "environmental_data", "regulatory_screening",
    "impact_analysis", "report_synthesis",
]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_agent_outputs_api.py::test_load_outputs_after_save tests/test_agent_outputs_api.py::test_load_outputs_no_outputs tests/test_agent_outputs_api.py::test_load_outputs_project_not_found -v
```

Expected: FAIL — GET endpoint doesn't exist yet.

- [ ] **Step 3: Add GET endpoint to main.py**

Add after the POST endpoint:

```python
@app.get("/api/projects/{project_id}/outputs")
def load_project_outputs(project_id: int):
    conn = _get_connection()
    try:
        cur = conn.cursor()
        # Verify project exists
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Project not found")

        agent_outputs = {}
        agent_costs = {}
        for agent_key, table_name in AGENT_OUTPUT_TABLES.items():
            cur.execute(
                f"SELECT output, model, input_tokens, output_tokens, cost_usd FROM {table_name} WHERE project_id = %s",
                (project_id,),
            )
            row = cur.fetchone()
            if row is None:
                agent_outputs[agent_key] = None
                agent_costs[agent_key] = None
            else:
                agent_outputs[agent_key] = row[0]
                if row[1] is not None:
                    agent_costs[agent_key] = {
                        "model": row[1],
                        "input_tokens": row[2],
                        "output_tokens": row[3],
                        "cost_usd": float(row[4]) if row[4] is not None else None,
                    }
                else:
                    agent_costs[agent_key] = None

        return {"agent_outputs": agent_outputs, "agent_costs": agent_costs}
    finally:
        cur.close()
        conn.close()
```

- [ ] **Step 4: Run all test_agent_outputs_api tests**

```bash
cd backend && python -m pytest tests/test_agent_outputs_api.py -v
```

Expected: ALL PASS (6 tests total).

- [ ] **Step 5: Run the full backend test suite to check for regressions**

```bash
cd backend && python -m pytest --tb=short
```

Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_agent_outputs_api.py
git commit -m "feat(api): add GET /api/projects/{id}/outputs endpoint"
```

---

### Task 4: Wire `currentProjectId` state in App.jsx

**Files:**
- Modify: `frontend/src/App.jsx:18-28` (add state)
- Modify: `frontend/src/App.jsx:107-115` (pass callbacks to ProjectForm)
- Modify: `frontend/src/components/ProjectForm.jsx:17` (accept new props)
- Modify: `frontend/src/components/ProjectForm.jsx:34-53` (set ID on save)
- Modify: `frontend/src/components/ProjectForm.jsx:55-59` (set ID on load)

- [ ] **Step 1: Add `currentProjectId` state to App.jsx**

In `frontend/src/App.jsx`, add after the `agentCosts` state (line 28):

```javascript
const [currentProjectId, setCurrentProjectId] = useState(null)
```

- [ ] **Step 2: Pass callbacks to ProjectForm**

Update the `<ProjectForm>` JSX in `App.jsx` (lines 107-115) to pass the new callback and state setters:

```jsx
<ProjectForm
  onResult={handleResult}
  onPipelineUpdate={handlePipelineUpdate}
  onStepsUpdate={handleStepsUpdate}
  onLog={handleLog}
  onRunningChange={handleRunningChange}
  modelSelections={selections}
  onCostUpdate={handleCostUpdate}
  onProjectIdChange={setCurrentProjectId}
  onLoadOutputs={(outputs, costs, pipelineStatus) => {
    setAgentOutputs(outputs)
    setAgentCosts(costs)
    setPipelineState(pipelineStatus)
    // Reconstruct results for ResultsPanel
    const hasAnyOutput = Object.values(outputs).some(v => v !== null)
    if (hasAnyOutput) {
      setResults({
        impact_matrix: outputs.impact_analysis || {},
        regulations: outputs.regulatory_screening || [],
        report: outputs.report_synthesis || {},
      })
    } else {
      setResults(null)
    }
  }}
/>
```

- [ ] **Step 3: Wire ProjectForm to set project ID on save**

In `frontend/src/components/ProjectForm.jsx`, update the function signature (line 17) to accept the new props:

```javascript
export default function ProjectForm({ onResult, onPipelineUpdate, onStepsUpdate, onLog, onRunningChange, modelSelections, onCostUpdate, onProjectIdChange, onLoadOutputs }) {
```

In `handleSave` (line 34-53), after `setSavedProjects`, add:

```javascript
onProjectIdChange?.(project.id)
```

- [ ] **Step 4: Wire ProjectForm to set project ID on load and fetch outputs**

Replace the `handleLoad` function (lines 55-59) with:

```javascript
const handleLoad = async (project) => {
  setProjectName(project.name)
  setCoordinates(project.coordinates)
  setDescription(project.description || '')
  onProjectIdChange?.(project.id)

  // Fetch saved agent outputs
  try {
    const res = await fetch(`${apiBase}/api/projects/${project.id}/outputs`)
    if (!res.ok) return
    const data = await res.json()

    const outputs = data.agent_outputs || {}
    const costs = data.agent_costs || {}

    // Build pipeline status: "complete" if output exists, "idle" otherwise
    const pipelineStatus = {}
    const agentNames = [
      'project_parser', 'environmental_data', 'regulatory_screening',
      'impact_analysis', 'report_synthesis',
    ]
    for (const name of agentNames) {
      pipelineStatus[name] = outputs[name] ? 'complete' : 'idle'
    }

    // Reconstruct agentCosts to match the SSE shape (include "agent" key)
    const formattedCosts = {}
    for (const name of agentNames) {
      if (costs[name]) {
        formattedCosts[name] = { agent: name, ...costs[name] }
      }
    }

    onLoadOutputs?.(outputs, formattedCosts, pipelineStatus)
  } catch {
    // best-effort — form fields are already loaded
  }
}
```

- [ ] **Step 5: Clear project ID when form fields are manually edited**

Add `onProjectIdChange?.(null)` to the `onChange` handlers for project name, coordinates, and description inputs. In the JSX for the three inputs, update:

For project name input (around line 199):
```javascript
onChange={(e) => { setProjectName(e.target.value); onProjectIdChange?.(null) }}
```

For coordinates input (around line 225):
```javascript
onChange={(e) => { setCoordinates(e.target.value); onProjectIdChange?.(null) }}
```

For description textarea (around line 240):
```javascript
onChange={(e) => { setDescription(e.target.value); onProjectIdChange?.(null) }}
```

Also for preset buttons (around line 213):
```javascript
onClick={() => { setCoordinates(loc.coordinates); onProjectIdChange?.(null) }}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.jsx frontend/src/components/ProjectForm.jsx
git commit -m "feat(frontend): wire currentProjectId state and load outputs on project load"
```

---

### Task 5: Add "SAVE RESULTS" button to App.jsx

**Files:**
- Modify: `frontend/src/App.jsx:133-136` (add button below ResultsPanel)
- Modify: `frontend/src/App.jsx` (add handler and state)

- [ ] **Step 1: Add save results state and handler to App.jsx**

In `frontend/src/App.jsx`, add after the `currentProjectId` state:

```javascript
const [saveResultsFlash, setSaveResultsFlash] = useState(null) // null | 'saving' | 'saved' | 'error'
```

Add the handler function (after `handleCommand`):

```javascript
const handleSaveResults = async () => {
  if (!currentProjectId) {
    setSaveResultsFlash('error')
    setTimeout(() => setSaveResultsFlash(null), 2000)
    return
  }
  setSaveResultsFlash('saving')
  try {
    const apiBase = import.meta.env.VITE_API_URL ?? ''
    const res = await fetch(`${apiBase}/api/projects/${currentProjectId}/outputs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_outputs: agentOutputs,
        agent_costs: agentCosts,
      }),
    })
    if (!res.ok) throw new Error('save failed')
    setSaveResultsFlash('saved')
    setTimeout(() => setSaveResultsFlash(null), 1500)
  } catch {
    setSaveResultsFlash('error')
    setTimeout(() => setSaveResultsFlash(null), 2000)
  }
}
```

- [ ] **Step 2: Add the button JSX below ResultsPanel**

Replace the `colMiddleBottom` div (lines 133-135):

```jsx
<div style={styles.colMiddleBottom}>
  <ResultsPanel results={results} />
  {!running && Object.keys(agentOutputs).length > 0 && (
    <button
      onClick={handleSaveResults}
      disabled={saveResultsFlash === 'saving'}
      style={{
        ...styles.saveResultsBtn,
        ...(saveResultsFlash === 'saved' ? styles.saveResultsBtnSaved : {}),
        ...(saveResultsFlash === 'error' ? styles.saveResultsBtnError : {}),
      }}
    >
      {saveResultsFlash === 'saving' ? 'SAVING...'
        : saveResultsFlash === 'saved' ? 'SAVED!'
        : saveResultsFlash === 'error' ? 'SAVE PROJECT FIRST'
        : 'SAVE RESULTS'}
    </button>
  )}
</div>
```

- [ ] **Step 3: Add styles for the save results button**

Add to the `styles` object in `App.jsx`:

```javascript
saveResultsBtn: {
  width: '100%',
  marginTop: '12px',
  padding: '10px',
  background: 'transparent',
  color: 'var(--green-primary)',
  border: '1px solid var(--green-primary)',
  borderRadius: '4px',
  fontFamily: 'var(--font-mono)',
  fontSize: '11px',
  fontWeight: 600,
  letterSpacing: '2px',
  cursor: 'pointer',
  transition: 'background 0.15s, color 0.15s',
},
saveResultsBtnSaved: {
  background: 'var(--green-primary)',
  color: '#0a0a0a',
},
saveResultsBtnError: {
  borderColor: '#ff4444',
  color: '#ff4444',
},
```

- [ ] **Step 4: Test manually in the browser**

1. Start backend: `cd backend && uvicorn main:app --reload --port 5050`
2. Start frontend: `cd frontend && npm run dev`
3. Open http://localhost:5173
4. Enter project details, click "RUN PIPELINE", wait for completion
5. Verify "SAVE RESULTS" button appears below OUTPUT section
6. Click "SAVE RESULTS" without saving project first — verify red "SAVE PROJECT FIRST" flash
7. Click "SAVE PROJECT", then "SAVE RESULTS" — verify green "SAVED!" flash
8. Click "LOAD" on the saved project — verify pipeline outputs are restored

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat(frontend): add SAVE RESULTS button with error handling"
```

---

### Task 6: End-to-end verification and cleanup

**Files:**
- All modified files

- [ ] **Step 1: Run backend tests**

```bash
cd backend && python -m pytest --tb=short
```

Expected: ALL PASS.

- [ ] **Step 2: Run frontend dev server and verify full flow**

Full golden path:
1. Enter project details
2. Click "SAVE PROJECT" — project appears in saved list
3. Click "RUN PIPELINE" — wait for completion
4. "SAVE RESULTS" button appears — click it — "SAVED!" flash
5. Refresh the page
6. Click "LOAD" on the saved project — form fields populate AND pipeline outputs/results restore
7. Run pipeline again — click "SAVE RESULTS" — overwrites previous outputs
8. Load again — see the updated outputs

Edge cases:
1. Click "SAVE RESULTS" without saving project — red "SAVE PROJECT FIRST"
2. Load a project that has never been run — pipeline stays idle, no outputs
3. Delete a project — reload page — confirm no orphan rows in output tables (check via VIEW DB)

- [ ] **Step 3: Commit any fixes**

If any issues found during verification, fix and commit.
