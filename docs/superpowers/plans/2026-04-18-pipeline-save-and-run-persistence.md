# Pipeline Save & Run Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit SAVE RESULTS button after pipeline completion, persist one run per project, auto-populate outputs and evaluation scores on project load, and improve text contrast throughout the UI.

**Architecture:** A new `pipeline_runs` table anchors a saved run to a project (one UNIQUE row per project). Saving calls a new `POST /api/projects/{id}/save-run` endpoint that upserts `pipeline_runs` + all 5 agent output tables atomically. The pipeline no longer auto-saves — `project_id` is kept only for RAG scoping. Evaluations auto-populate via a new `GET /api/evaluations/score/{project_id}` endpoint that `EvaluatePanel` already calls.

**Tech Stack:** FastAPI, psycopg2 (raw SQL), React 18 (inline CSS), PostgreSQL

---

## File Map

| File | Change |
|------|--------|
| `backend/db/vector_store.py` | Add `pipeline_runs` CREATE TABLE to `init_db()` |
| `backend/db/evaluation_scores.py` | Add `ALTER TABLE evaluation_scores ADD COLUMN run_id` migration |
| `backend/pipeline.py` | Remove auto-save UPSERT block (lines 455–499) |
| `backend/main.py` | Add 3 endpoints: `GET /api/projects/{id}/run`, `POST /api/projects/{id}/save-run`, `GET /api/evaluations/score/{id}` |
| `frontend/src/App.jsx` | Update `handleSaveResults` → new endpoint + 409 handling + overwrite warning; style SAVE RESULTS as solid green |
| `frontend/src/components/EvaluatePanel.jsx` | Fetch run status on project change; gate `canEvaluate` on saved run; update button label |
| `frontend/src/index.css` | Raise `--text-muted` and `--text-secondary` contrast |

---

## Task 1: Add `pipeline_runs` table to `init_db()`

**Files:**
- Modify: `backend/db/vector_store.py`

- [ ] **Step 1: Add CREATE TABLE after the agent output tables loop**

In `backend/db/vector_store.py`, inside `init_db()`, add after the `conn.commit()` on line 74 (before `cur.close()`):

```python
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id         SERIAL PRIMARY KEY,
                project_id INTEGER UNIQUE NOT NULL
                    REFERENCES projects(id) ON DELETE CASCADE,
                saved_at   TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        conn.commit()
```

Place it immediately after the `for table_name in (...)` loop's `conn.commit()` call, still before `cur.close()`.

- [ ] **Step 2: Verify the server starts without errors**

```bash
cd backend && python -c "from db.vector_store import init_db; init_db(); print('OK')"
```

Expected: `OK` printed, no exception. (Requires `DATABASE_URL` to be set.)

- [ ] **Step 3: Commit**

```bash
git add backend/db/vector_store.py
git commit -m "feat: add pipeline_runs table to init_db"
```

---

## Task 2: Add `run_id` column to `evaluation_scores`

**Files:**
- Modify: `backend/db/evaluation_scores.py`

- [ ] **Step 1: Add idempotent migration inside `init_evaluation_scores_schema`**

In `backend/db/evaluation_scores.py`, inside `init_evaluation_scores_schema`, add before the final `conn.commit()` on line 64:

```python
        # Idempotent migration: add run_id FK to pipeline_runs (nullable).
        cur.execute("""
            ALTER TABLE evaluation_scores
              ADD COLUMN IF NOT EXISTS run_id INTEGER
                REFERENCES pipeline_runs(id) ON DELETE SET NULL
        """)
```

- [ ] **Step 2: Verify**

```bash
cd backend && python -c "
from db.vector_store import _get_connection, init_db
from db.evaluation_scores import init_evaluation_scores_schema
init_db()
conn = _get_connection()
init_evaluation_scores_schema(conn)
conn.close()
print('OK')
"
```

Expected: `OK`, no exception.

- [ ] **Step 3: Commit**

```bash
git add backend/db/evaluation_scores.py
git commit -m "feat: add run_id FK column to evaluation_scores"
```

---

## Task 3: Remove pipeline auto-save

**Files:**
- Modify: `backend/pipeline.py`

- [ ] **Step 1: Delete the auto-save block**

In `backend/pipeline.py`, find and remove the entire block starting at line 455:

```python
                # Persist agent output to DB if a project_id was provided
                if project_id is not None and agent_output is not None:
                    _AGENT_TABLE_MAP = {
                        "project_parser": "project_parser_outputs",
                        ...
                    }
                    table_name = _AGENT_TABLE_MAP.get(agent_key)
                    if table_name:
                        try:
                            ...
                        except Exception as _e:
                            logger.warning(...)
```

Remove the entire `if project_id is not None and agent_output is not None:` block and everything inside it (through the `except` / `logger.warning` at line ~499). Do not remove any other code.

- [ ] **Step 2: Verify pipeline module imports cleanly**

```bash
cd backend && python -c "from pipeline import stream_eia_pipeline; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add backend/pipeline.py
git commit -m "refactor: remove pipeline auto-save (now explicit via save-run endpoint)"
```

---

## Task 4: Add `GET /api/projects/{project_id}/run` endpoint

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add endpoint after `DELETE /api/projects/{project_id}`**

Find the `DELETE /api/projects/{project_id}` endpoint in `main.py`. Add the following immediately after it:

```python
@app.get("/api/projects/{project_id}/run")
def get_project_run(project_id: int):
    conn = _get_connection()
    cur = None
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, saved_at FROM pipeline_runs WHERE project_id = %s",
            (project_id,),
        )
        row = cur.fetchone()
        if row is None:
            return {"run": None}
        return {"run_id": row[0], "saved_at": row[1].isoformat()}
    finally:
        if cur is not None:
            cur.close()
        conn.close()
```

- [ ] **Step 2: Verify the server starts**

```bash
cd backend && python -c "import main; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: add GET /api/projects/{id}/run endpoint"
```

---

## Task 5: Add `POST /api/projects/{project_id}/save-run` endpoint

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add `SaveRunRequest` model near `SaveOutputsRequest`**

Find `class SaveOutputsRequest` in `main.py`. Add immediately before it:

```python
class SaveRunRequest(BaseModel):
    agent_outputs: dict
    agent_costs: dict = Field(default_factory=dict)
```

- [ ] **Step 2: Add the endpoint after `GET /api/projects/{project_id}/run`**

```python
@app.post("/api/projects/{project_id}/save-run")
def save_run(project_id: int, req: SaveRunRequest, force: bool = False):
    from fastapi.responses import JSONResponse
    import json as _json

    conn = _get_connection()
    cur = None
    try:
        cur = conn.cursor()

        cur.execute(
            "SELECT id, saved_at FROM pipeline_runs WHERE project_id = %s",
            (project_id,),
        )
        existing = cur.fetchone()
        if existing and not force:
            return JSONResponse(
                status_code=409,
                content={"exists": True, "saved_at": existing[1].isoformat()},
            )

        cur.execute(
            """
            INSERT INTO pipeline_runs (project_id, saved_at)
            VALUES (%s, NOW())
            ON CONFLICT (project_id) DO UPDATE SET saved_at = NOW()
            RETURNING id, saved_at
            """,
            (project_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("save_run: pipeline_runs upsert returned no row")
        run_id, saved_at = row

        for agent_key, table_name in AGENT_OUTPUT_TABLES:
            if table_name not in _ALLOWED_OUTPUT_TABLES:
                continue
            output = req.agent_outputs.get(agent_key)
            if output is None:
                continue
            costs = req.agent_costs.get(agent_key, {})
            cur.execute(
                f'INSERT INTO "{table_name}" '
                f"(project_id, output, model, input_tokens, output_tokens, cost_usd, saved_at) "
                f"VALUES (%s, %s, %s, %s, %s, %s, NOW()) "
                f"ON CONFLICT (project_id) DO UPDATE SET "
                f"output = EXCLUDED.output, model = EXCLUDED.model, "
                f"input_tokens = EXCLUDED.input_tokens, "
                f"output_tokens = EXCLUDED.output_tokens, "
                f"cost_usd = EXCLUDED.cost_usd, "
                f"saved_at = EXCLUDED.saved_at",
                (
                    project_id,
                    _json.dumps(output),
                    costs.get("model"),
                    costs.get("input_tokens"),
                    costs.get("output_tokens"),
                    costs.get("cost_usd"),
                ),
            )

        conn.commit()
        return {"run_id": run_id, "saved_at": saved_at.isoformat()}
    finally:
        if cur is not None:
            cur.close()
        conn.close()
```

- [ ] **Step 3: Verify**

```bash
cd backend && python -c "import main; print('OK')"
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat: add POST /api/projects/{id}/save-run endpoint with 409 overwrite guard"
```

---

## Task 6: Add `GET /api/evaluations/score/{project_id}` endpoint

**Files:**
- Modify: `backend/main.py`

Note: `EvaluatePanel.jsx` already calls this URL on project change. `get_score` already exists in `db/evaluation_scores.py` and returns a formatted dict.

- [ ] **Step 1: Add endpoint before `POST /api/evaluations/score`**

Find `@app.post("/api/evaluations/score")` in `main.py`. Add immediately before it:

```python
@app.get("/api/evaluations/score/{project_id}")
def get_evaluation_score(project_id: int):
    conn = _get_connection()
    try:
        result = get_score(conn, project_id)
        if result is None:
            raise HTTPException(status_code=404, detail="No scores found")
        return result
    finally:
        conn.close()
```

- [ ] **Step 2: Verify**

```bash
cd backend && python -c "import main; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: add GET /api/evaluations/score/{project_id} for auto-populate"
```

---

## Task 7: Update `App.jsx` — SAVE RESULTS button and overwrite warning

**Files:**
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Add `pendingOverwrite` state**

After line 34 (`const [saveResultsFlash, setSaveResultsFlash] = useState(null)`), add:

```javascript
  const [pendingOverwrite, setPendingOverwrite] = useState(null) // null | {saved_at}
```

- [ ] **Step 2: Replace `handleSaveResults`**

Replace the entire `handleSaveResults` function (lines 120–144) with:

```javascript
  const handleSaveResults = async (force = false) => {
    if (!currentProjectId) {
      setSaveResultsFlash('error')
      setTimeout(() => setSaveResultsFlash(null), 2000)
      return
    }
    setSaveResultsFlash('saving')
    setPendingOverwrite(null)
    try {
      const apiBase = import.meta.env.VITE_API_URL ?? ''
      const url = `${apiBase}/api/projects/${currentProjectId}/save-run${force ? '?force=true' : ''}`
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_outputs: agentOutputs,
          agent_costs: agentCosts,
        }),
      })
      if (res.status === 409) {
        const body = await res.json()
        setSaveResultsFlash(null)
        setPendingOverwrite({ saved_at: body.saved_at })
        return
      }
      if (!res.ok) throw new Error('save failed')
      setSaveResultsFlash('saved')
      setTimeout(() => setSaveResultsFlash(null), 1500)
    } catch {
      setSaveResultsFlash('error')
      setTimeout(() => setSaveResultsFlash(null), 2000)
    }
  }
```

- [ ] **Step 3: Replace the SAVE RESULTS button render block**

Find and replace the button block (lines 244–259):

```jsx
              {!running && Object.keys(agentOutputs).length > 0 && (
                <div style={{ marginTop: '12px' }}>
                  <button
                    onClick={() => handleSaveResults(false)}
                    disabled={saveResultsFlash === 'saving'}
                    style={{
                      ...styles.saveResultsBtn,
                      ...(saveResultsFlash === 'saved' ? styles.saveResultsBtnSaved : {}),
                      ...(saveResultsFlash === 'error' ? styles.saveResultsBtnError : {}),
                    }}
                  >
                    {saveResultsFlash === 'saving' ? 'SAVING...'
                      : saveResultsFlash === 'saved' ? 'SAVED ✓'
                      : saveResultsFlash === 'error' ? 'SAVE PROJECT FIRST'
                      : 'SAVE RESULTS'}
                  </button>
                  {pendingOverwrite && (
                    <div style={styles.overwriteWarning}>
                      <span>Results saved {new Date(pendingOverwrite.saved_at).toLocaleString()} already exist.</span>
                      <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
                        <button
                          style={styles.overwriteConfirmBtn}
                          onClick={() => handleSaveResults(true)}
                        >
                          CONFIRM OVERWRITE
                        </button>
                        <button
                          style={styles.overwriteCancelBtn}
                          onClick={() => setPendingOverwrite(null)}
                        >
                          CANCEL
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
```

- [ ] **Step 4: Update `saveResultsBtn` style and add new styles**

Replace the `saveResultsBtn`, `saveResultsBtnSaved`, and `saveResultsBtnError` entries in the `styles` object with:

```javascript
  saveResultsBtn: {
    width: '100%',
    padding: '12px',
    background: 'var(--green-primary)',
    color: '#0a0a0a',
    border: '1px solid var(--green-primary)',
    borderRadius: '4px',
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    fontWeight: 700,
    letterSpacing: '2px',
    cursor: 'pointer',
    transition: 'opacity 0.15s',
  },
  saveResultsBtnSaved: {
    opacity: 0.8,
  },
  saveResultsBtnError: {
    background: 'transparent',
    color: '#ff4444',
    borderColor: '#ff4444',
  },
  overwriteWarning: {
    marginTop: '10px',
    padding: '10px 12px',
    background: 'rgba(255,170,0,0.08)',
    border: '1px solid #ffaa00',
    borderRadius: '4px',
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: '#ffaa00',
    lineHeight: 1.5,
  },
  overwriteConfirmBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    letterSpacing: '1px',
    color: '#0a0a0a',
    background: '#ffaa00',
    border: '1px solid #ffaa00',
    borderRadius: '3px',
    padding: '4px 10px',
    cursor: 'pointer',
  },
  overwriteCancelBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    letterSpacing: '1px',
    color: 'var(--text-muted)',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '3px',
    padding: '4px 10px',
    cursor: 'pointer',
  },
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat: SAVE RESULTS button with 409 overwrite warning and solid green style"
```

---

## Task 8: Update `EvaluatePanel.jsx` — gate on saved run + button label

**Files:**
- Modify: `frontend/src/components/EvaluatePanel.jsx`

Note: `EvaluatePanel` already fetches `GET /api/evaluations/score/${selectedProject.id}` on project change (line 182). We only need to add the run-existence check and update `canEvaluate` + button label.

- [ ] **Step 1: Add `savedRun` state**

After line 168 (`const [showDetail, setShowDetail] = useState(false)`), add:

```javascript
  const [savedRun, setSavedRun] = useState(null) // null | {run_id, saved_at}
```

- [ ] **Step 2: Fetch run status on project change**

In the `useEffect` that runs when `selectedProject` changes (starting at line 171), add a fetch for the run after the existing fetches. The effect currently ends at line 186. Add inside the `if (!selectedProject) return` block — reset `savedRun` too — and add a fetch after the existing two fetches:

Replace the entire `useEffect` (lines 171–186) with:

```javascript
  useEffect(() => {
    setScores(null)
    setError(null)
    setLinkedDocs([])
    setSavedRun(null)
    if (!selectedProject) return

    fetch(`${apiBase}/api/evaluations?project_id=${selectedProject.id}`)
      .then(r => r.json())
      .then(data => setLinkedDocs(data.documents || []))
      .catch(() => {})

    fetch(`${apiBase}/api/evaluations/score/${selectedProject.id}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setScores(data) })
      .catch(() => {})

    fetch(`${apiBase}/api/projects/${selectedProject.id}/run`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data?.run_id) setSavedRun(data) })
      .catch(() => {})
  }, [selectedProject?.id])
```

- [ ] **Step 3: Update `canEvaluate` and button label**

Replace line 209:

```javascript
  const canEvaluate = selectedProject && linkedDocs.length > 0 && !loading
```

with:

```javascript
  const canEvaluate = selectedProject && linkedDocs.length > 0 && savedRun !== null && !loading
```

Replace the button label expression on line 249:

```javascript
        {loading ? 'EVALUATING…' : scores ? 'RE-EVALUATE' : 'EVALUATE'}
```

with:

```javascript
        {loading ? 'EVALUATING…' : scores ? 'RE-EVALUATE' : savedRun ? 'IMPORT RUN' : 'EVALUATE'}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/EvaluatePanel.jsx
git commit -m "feat: gate EvaluatePanel on saved pipeline run, show IMPORT RUN label"
```

---

## Task 9: Gray text → white in `index.css`

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Raise contrast on muted and secondary text**

In `frontend/src/index.css`, inside `:root`, change:

```css
  --text-secondary: #888888;
  --text-muted: #444444;
```

to:

```css
  --text-secondary: #cccccc;
  --text-muted: #aaaaaa;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/index.css
git commit -m "fix: raise --text-muted and --text-secondary contrast for readability"
```

---

## Task 10: Update documentation

**Files:**
- Modify: `DATA_MODEL.md`
- Modify: `docs/eval-pipeline.md`

- [ ] **Step 1: Add `pipeline_runs` to DATA_MODEL.md**

Add a new table entry for `pipeline_runs`:

```markdown
### `pipeline_runs`
One row per project representing the user's explicitly saved pipeline run.

| Column | Type | Notes |
|--------|------|-------|
| id | SERIAL PK | |
| project_id | INTEGER UNIQUE FK→projects | ON DELETE CASCADE |
| saved_at | TIMESTAMPTZ | Updated on overwrite |
```

Also add `run_id` to the `evaluation_scores` table entry.

- [ ] **Step 2: Add new endpoints to `docs/eval-pipeline.md`**

In the API reference table, add:

```
| GET  | /api/projects/{id}/run       | Returns saved run metadata or null |
| POST | /api/projects/{id}/save-run  | Save/overwrite pipeline outputs; ?force=true to overwrite |
| GET  | /api/evaluations/score/{id}  | Fetch cached evaluation scores for a project |
```

- [ ] **Step 3: Commit**

```bash
git add DATA_MODEL.md docs/eval-pipeline.md
git commit -m "docs: document pipeline_runs table and new save/score endpoints"
```
