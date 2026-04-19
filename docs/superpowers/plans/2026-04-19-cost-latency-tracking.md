# Cost & Latency Tracking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-agent latency tracking, store all runs per project in the DB, gate RUN PIPELINE behind project save, and expose Cost and Latency pages via an EVALUATIONS dropdown.

**Architecture:** Extend `pipeline_runs` and all 5 agent output tables with new columns via startup migrations (drop UNIQUE constraints, add `run_id`/`duration_ms`/aggregate columns); time agents in `pipeline.py` and emit `duration_ms` in SSE; rewrite `save_run` to always INSERT a fresh run (no more conflict logic); add four `/api/metrics/*` GET routes; build a shared `MetricsView` React component rendered at two nav entries under an EVALUATIONS dropdown.

**Tech Stack:** Python 3.11, FastAPI, psycopg2, React 18.3.1, Vite, inline CSS (no new dependencies)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/db/vector_store.py` | Modify | Drop UNIQUE constraints; add `run_id`, `duration_ms`, and aggregate columns via `init_db()` |
| `backend/pipeline.py` | Modify | Time each `agent.run()` call; emit `duration_ms` in `agent_complete`; emit `started_at` in `pipeline_start` |
| `backend/main.py` | Modify | Rewrite `save_run` (no UNIQUE, store `run_id`/`duration_ms`/totals); add four `/api/metrics/*` endpoints |
| `frontend/src/components/ProjectForm.jsx` | Modify | Accept `projectId` + `onDurationUpdate` + `onPipelineStartedAt` props; disable RUN PIPELINE when no project; propagate new SSE fields |
| `frontend/src/App.jsx` | Modify | Pass `projectId` to ProjectForm; add `agentDurations`/`pipelineStartedAt` state; update save-run body; replace EVALUATIONS button with dropdown; add `cost`/`latency` view routes; remove `pendingOverwrite` dialog |
| `frontend/src/components/AgentPipeline.jsx` | Modify | Accept `agentDurations` prop; add latency chip with live timer |
| `frontend/src/pages/MetricsView.jsx` | Create | Shared Cost/Latency page: overview stats + SVG bar chart + model table + run drill-down |

---

### Task 1: DB Schema Migrations

**Files:**
- Modify: `backend/db/vector_store.py`

All changes are applied at startup via `init_db()`. `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` and `DROP CONSTRAINT IF EXISTS` are both idempotent — safe to run on existing databases.

- [ ] **Step 1: Update `CREATE TABLE pipeline_runs`**

In `init_db()`, find the `CREATE TABLE IF NOT EXISTS pipeline_runs` block and replace it:

```python
cur.execute("""
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        id SERIAL PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        started_at TIMESTAMPTZ,
        finished_at TIMESTAMPTZ,
        total_duration_ms INTEGER,
        total_cost_usd NUMERIC(10,6),
        total_input_tokens INTEGER,
        total_output_tokens INTEGER,
        saved_at TIMESTAMPTZ DEFAULT NOW()
    )
""")
```

- [ ] **Step 2: Update CREATE TABLE for each agent output table**

Find the loop (or individual statements) that creates the 5 agent output tables. Remove `UNIQUE (project_id)` and add `run_id` and `duration_ms` to each:

```python
for table_name in [
    "project_parser_outputs",
    "environmental_data_outputs",
    "regulatory_screening_outputs",
    "impact_analysis_outputs",
    "report_synthesis_outputs",
]:
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id SERIAL PRIMARY KEY,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            run_id INTEGER REFERENCES pipeline_runs(id),
            output JSONB NOT NULL,
            model TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cost_usd NUMERIC(10,6),
            duration_ms INTEGER,
            saved_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
```

- [ ] **Step 3: Add ALTER TABLE migrations for existing installs**

After all CREATE TABLE statements in `init_db()`, add these idempotent migrations:

```python
# pipeline_runs — drop unique, add aggregate columns
cur.execute("ALTER TABLE pipeline_runs DROP CONSTRAINT IF EXISTS pipeline_runs_project_id_key")
for col in [
    "started_at TIMESTAMPTZ",
    "finished_at TIMESTAMPTZ",
    "total_duration_ms INTEGER",
    "total_cost_usd NUMERIC(10,6)",
    "total_input_tokens INTEGER",
    "total_output_tokens INTEGER",
]:
    cur.execute(f"ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS {col}")

# agent output tables — drop unique, add run_id and duration_ms
for tbl in [
    "project_parser_outputs",
    "environmental_data_outputs",
    "regulatory_screening_outputs",
    "impact_analysis_outputs",
    "report_synthesis_outputs",
]:
    cur.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS {tbl}_project_id_key")
    cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS run_id INTEGER REFERENCES pipeline_runs(id)")
    cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS duration_ms INTEGER")
```

- [ ] **Step 4: Start backend and verify**

```bash
cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 5050
```

Expected: server starts with no errors. Open VIEW DB — `pipeline_runs` should show columns `started_at`, `finished_at`, `total_duration_ms`, `total_cost_usd`, `total_input_tokens`, `total_output_tokens`. Each agent output table should show `run_id` and `duration_ms`.

- [ ] **Step 5: Commit**

```bash
git add backend/db/vector_store.py
git commit -m "feat: add run_id, duration_ms, and pipeline aggregate columns via startup migrations"
```

---

### Task 2: Pipeline Agent Timing

**Files:**
- Modify: `backend/pipeline.py`

- [ ] **Step 1: Add imports if missing**

At the top of `pipeline.py`, ensure these are present:

```python
import time
from datetime import datetime, timezone
```

- [ ] **Step 2: Emit `started_at` in `pipeline_start` event**

Find the `pipeline_start` yield (around line 349). Add `started_at`:

```python
yield _sse_event("pipeline_start", {
    "pipeline_status": dict(pipeline_status),
    "agent_steps": {k: list(v) for k, v in agent_steps.items()},
    "started_at": datetime.now(timezone.utc).isoformat(),
})
```

- [ ] **Step 3: Time each agent and add `duration_ms` to `agent_complete`**

In the agent execution loop, find where `agent.run(state)` is called. Wrap it:

```python
_agent_start = time.time()
state = agent.run(state)
_agent_duration_ms = int((time.time() - _agent_start) * 1000)
```

Then find the `agent_complete` yield (around line 432) and add `duration_ms`:

```python
yield _sse_event("agent_complete", {
    "agent": agent_key,
    "duration_ms": _agent_duration_ms,
    "pipeline_status": dict(pipeline_status),
    "steps": agent_steps[agent_key],
    "output": agent_output,
})
```

- [ ] **Step 4: Verify in browser devtools**

Run a pipeline. In Chrome DevTools → Network → `/api/run` → EventStream, confirm:
- `pipeline_start` includes `started_at` (ISO string)
- Each `agent_complete` includes `duration_ms` (positive integer)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline.py
git commit -m "feat: emit duration_ms per agent and started_at in pipeline SSE events"
```

---

### Task 3: Rewrite save_run + Update get_project_outputs

**Files:**
- Modify: `backend/main.py`

The `save_run` endpoint currently uses `ON CONFLICT (project_id)` for pipeline_runs and each agent output table. Since the UNIQUE constraints are now dropped, change it to always INSERT a fresh row. Remove the `force` flag and the 409 response entirely.

- [ ] **Step 1: Update `SaveRunRequest`**

Find `SaveRunRequest` (around line 458):

```python
class SaveRunRequest(BaseModel):
    agent_outputs: dict
    agent_costs: dict = Field(default_factory=dict)
    agent_durations: dict = Field(default_factory=dict)  # agent_key -> int (ms)
    started_at: str | None = None  # ISO 8601 from pipeline_start SSE event
```

- [ ] **Step 2: Rewrite `save_run`**

Replace the entire `save_run` function body (lines ~463–527). Remove the `force: bool = False` parameter:

```python
@app.post("/api/projects/{project_id}/save-run")
def save_run(project_id: int, req: SaveRunRequest):
    conn = _get_connection()
    cur = None
    try:
        cur = conn.cursor()

        total_cost = sum(
            float(req.agent_costs.get(k, {}).get("cost_usd") or 0)
            for k, _ in AGENT_OUTPUT_TABLES
        )
        total_input = sum(
            int(req.agent_costs.get(k, {}).get("input_tokens") or 0)
            for k, _ in AGENT_OUTPUT_TABLES
        )
        total_output = sum(
            int(req.agent_costs.get(k, {}).get("output_tokens") or 0)
            for k, _ in AGENT_OUTPUT_TABLES
        )
        total_duration = sum(
            int(req.agent_durations.get(k) or 0)
            for k, _ in AGENT_OUTPUT_TABLES
        )

        started_at = None
        if req.started_at:
            try:
                started_at = datetime.fromisoformat(req.started_at.replace("Z", "+00:00"))
            except ValueError:
                pass

        cur.execute(
            """
            INSERT INTO pipeline_runs
                (project_id, started_at, finished_at, total_duration_ms,
                 total_cost_usd, total_input_tokens, total_output_tokens, saved_at)
            VALUES (%s, %s, NOW(), %s, %s, %s, %s, NOW())
            RETURNING id, saved_at
            """,
            (project_id, started_at, total_duration, total_cost, total_input, total_output),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("save_run: pipeline_runs insert returned no row")
        run_id, saved_at = row

        for agent_key, table_name in AGENT_OUTPUT_TABLES:
            if table_name not in _ALLOWED_OUTPUT_TABLES:
                continue
            output = req.agent_outputs.get(agent_key)
            if output is None:
                continue
            costs = req.agent_costs.get(agent_key) or {}
            duration_ms = req.agent_durations.get(agent_key)
            cur.execute(
                f'INSERT INTO "{table_name}" '
                f"(project_id, run_id, output, model, input_tokens, output_tokens, cost_usd, duration_ms, saved_at) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())",
                (
                    project_id,
                    run_id,
                    psycopg2.extras.Json(output),
                    costs.get("model"),
                    costs.get("input_tokens"),
                    costs.get("output_tokens"),
                    costs.get("cost_usd"),
                    duration_ms,
                ),
            )

        conn.commit()
        return {"run_id": run_id, "saved_at": saved_at.isoformat()}
    finally:
        if cur is not None:
            cur.close()
        conn.close()
```

Add `from datetime import datetime` at the top of `main.py` if not already there.

- [ ] **Step 3: Update `get_project_outputs` to prefer newest run_id**

In `get_project_outputs` (around line 398), the per-agent SELECT uses `ORDER BY saved_at DESC LIMIT 1`. Change to prefer rows tied to a run:

```python
cur.execute(
    f'SELECT output, model, input_tokens, output_tokens, cost_usd, saved_at '
    f'FROM "{table_name}" WHERE project_id = %s '
    f'ORDER BY run_id DESC NULLS LAST, saved_at DESC LIMIT 1',
    (project_id,),
)
```

- [ ] **Step 4: Fix `save_project_outputs` (POST `/api/projects/{project_id}/outputs`)**

This endpoint (around line 530) also uses `ON CONFLICT (project_id) DO UPDATE` on each agent output table. After dropping the UNIQUE constraint those clauses will error at runtime. Change each INSERT to a plain INSERT (no conflict clause):

```python
cur.execute(
    f"""
    INSERT INTO {table_name} (project_id, output, model, input_tokens, output_tokens, cost_usd)
    VALUES (%s, %s, %s, %s, %s, %s)
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
```

Note: this endpoint does not pass `run_id` or `duration_ms` — that's fine; those columns are nullable.

- [ ] **Step 5: Update `get_project_run` to return most recent run**

In `get_project_run` (around line 438), update the SELECT:

```python
cur.execute(
    "SELECT id, saved_at FROM pipeline_runs WHERE project_id = %s ORDER BY id DESC LIMIT 1",
    (project_id,),
)
```

- [ ] **Step 6: Verify two saves create two rows**

```bash
# Run twice with same project_id — should get different run_id each time
curl -s -X POST http://localhost:5050/api/projects/1/save-run \
  -H "Content-Type: application/json" \
  -d '{"agent_outputs":{"project_parser":{"test":true}},"agent_costs":{}}' | jq .run_id
curl -s -X POST http://localhost:5050/api/projects/1/save-run \
  -H "Content-Type: application/json" \
  -d '{"agent_outputs":{"project_parser":{"test":true}},"agent_costs":{}}' | jq .run_id
```

Expected: two different integers.

- [ ] **Step 7: Commit**

```bash
git add backend/main.py
git commit -m "feat: rewrite save_run to always insert new run with run_id, duration_ms, and totals"
```

---

### Task 4: Backend Metrics API Endpoints

**Files:**
- Modify: `backend/main.py`

Add four GET endpoints after the existing `save_run` function.

- [ ] **Step 1: Add `GET /api/metrics/overview`**

```python
@app.get("/api/metrics/overview")
def get_metrics_overview():
    conn = _get_connection()
    cur = None
    try:
        cur = conn.cursor()

        per_agent = []
        for agent_key, table_name in AGENT_OUTPUT_TABLES:
            assert table_name in _ALLOWED_OUTPUT_TABLES
            cur.execute(
                f'SELECT model, AVG(cost_usd)::float, AVG(duration_ms)::float, COUNT(*) '
                f'FROM "{table_name}" WHERE run_id IS NOT NULL GROUP BY model',
            )
            for row in cur.fetchall():
                per_agent.append({
                    "agent": agent_key,
                    "model": row[0],
                    "avg_cost_usd": float(row[1] or 0),
                    "avg_duration_ms": float(row[2] or 0),
                    "run_count": int(row[3]),
                })

        union_sql = " UNION ALL ".join(
            f'SELECT model, input_tokens, output_tokens, cost_usd FROM "{t}" WHERE run_id IS NOT NULL'
            for _, t in AGENT_OUTPUT_TABLES
        )
        cur.execute(
            f"SELECT model, SUM(input_tokens)::bigint, SUM(output_tokens)::bigint, SUM(cost_usd)::float "
            f"FROM ({union_sql}) AS all_outputs "
            f"WHERE model IS NOT NULL AND model <> '' "
            f"GROUP BY model ORDER BY SUM(cost_usd) DESC NULLS LAST"
        )
        per_model = [
            {
                "model": r[0],
                "total_input_tokens": int(r[1] or 0),
                "total_output_tokens": int(r[2] or 0),
                "total_cost_usd": float(r[3] or 0),
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT COUNT(*), SUM(total_cost_usd)::float, SUM(total_duration_ms)::bigint, "
            "AVG(total_cost_usd)::float, AVG(total_duration_ms)::float "
            "FROM pipeline_runs WHERE total_cost_usd IS NOT NULL"
        )
        r = cur.fetchone()
        totals = {
            "total_runs": int(r[0] or 0),
            "total_cost_usd": float(r[1] or 0),
            "total_duration_ms": int(r[2] or 0),
            "avg_cost_per_run": float(r[3] or 0),
            "avg_duration_per_run_ms": float(r[4] or 0),
        }

        return {"per_agent": per_agent, "per_model": per_model, "totals": totals}
    finally:
        if cur is not None:
            cur.close()
        conn.close()
```

- [ ] **Step 2: Add `GET /api/metrics/runs`**

```python
@app.get("/api/metrics/runs")
def get_all_runs():
    conn = _get_connection()
    cur = None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT pr.id, pr.project_id, pr.started_at, pr.finished_at,
                   pr.total_duration_ms, pr.total_cost_usd,
                   pr.total_input_tokens, pr.total_output_tokens,
                   p.name AS project_name
            FROM pipeline_runs pr
            LEFT JOIN projects p ON p.id = pr.project_id
            ORDER BY pr.id DESC
            """
        )
        return [
            {
                "id": r[0],
                "project_id": r[1],
                "started_at": r[2].isoformat() if r[2] else None,
                "finished_at": r[3].isoformat() if r[3] else None,
                "total_duration_ms": r[4],
                "total_cost_usd": float(r[5] or 0),
                "total_input_tokens": r[6],
                "total_output_tokens": r[7],
                "project_name": r[8],
            }
            for r in cur.fetchall()
        ]
    finally:
        if cur is not None:
            cur.close()
        conn.close()
```

- [ ] **Step 3: Add `GET /api/metrics/runs/{run_id}`**

```python
@app.get("/api/metrics/runs/{run_id}")
def get_run_detail(run_id: int):
    conn = _get_connection()
    cur = None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT pr.id, pr.project_id, pr.started_at, pr.finished_at,
                   pr.total_duration_ms, pr.total_cost_usd,
                   pr.total_input_tokens, pr.total_output_tokens,
                   p.name AS project_name
            FROM pipeline_runs pr
            LEFT JOIN projects p ON p.id = pr.project_id
            WHERE pr.id = %s
            """,
            (run_id,),
        )
        r = cur.fetchone()
        if r is None:
            raise HTTPException(status_code=404, detail="Run not found")
        run = {
            "id": r[0], "project_id": r[1],
            "started_at": r[2].isoformat() if r[2] else None,
            "finished_at": r[3].isoformat() if r[3] else None,
            "total_duration_ms": r[4],
            "total_cost_usd": float(r[5] or 0),
            "total_input_tokens": r[6],
            "total_output_tokens": r[7],
            "project_name": r[8],
        }
        agents = []
        for agent_key, table_name in AGENT_OUTPUT_TABLES:
            assert table_name in _ALLOWED_OUTPUT_TABLES
            cur.execute(
                f'SELECT model, input_tokens, output_tokens, cost_usd, duration_ms '
                f'FROM "{table_name}" WHERE run_id = %s',
                (run_id,),
            )
            row = cur.fetchone()
            if row:
                agents.append({
                    "agent": agent_key,
                    "model": row[0],
                    "input_tokens": int(row[1] or 0),
                    "output_tokens": int(row[2] or 0),
                    "cost_usd": float(row[3] or 0),
                    "duration_ms": row[4],
                })
        return {"run": run, "agents": agents}
    finally:
        if cur is not None:
            cur.close()
        conn.close()
```

- [ ] **Step 4: Add `GET /api/metrics/pricing`**

```python
@app.get("/api/metrics/pricing")
def get_pricing():
    from llm.pricing import MODEL_PRICING
    return {
        model_id: {
            "label": info["label"],
            "input_per_1m": info["input"],
            "output_per_1m": info["output"],
        }
        for model_id, info in MODEL_PRICING.items()
    }
```

- [ ] **Step 5: Test all four endpoints**

```bash
curl -s http://localhost:5050/api/metrics/overview | jq .totals
curl -s http://localhost:5050/api/metrics/runs | jq 'length'
curl -s http://localhost:5050/api/metrics/runs/1 | jq .run
curl -s http://localhost:5050/api/metrics/pricing | jq 'keys'
```

Expected: all return valid JSON without errors.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py
git commit -m "feat: add /api/metrics/overview, /runs, /runs/{id}, and /pricing endpoints"
```

---

### Task 5: Frontend Save Gate

**Files:**
- Modify: `frontend/src/components/ProjectForm.jsx`
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Add `projectId` to ProjectForm's prop signature**

`ProjectForm.jsx` function signature (line ~17). Add `projectId` at the end:

```javascript
export default function ProjectForm({ onResult, onPipelineUpdate, onStepsUpdate, onLog, onRunningChange, modelSelections, onCostUpdate, onProjectIdChange, onLoadOutputs, onProjectInfoChange, projectId }) {
```

- [ ] **Step 2: Disable RUN PIPELINE when `!projectId`**

Find the submit button (around line 284). Update `disabled` and add a disabled style. `styles.saveBtnDisabled` already exists in this file:

```javascript
<button
  type="submit"
  disabled={loading || !projectId}
  style={{
    ...styles.button,
    ...(loading ? styles.buttonLoading : {}),
    ...(!projectId && !loading ? styles.saveBtnDisabled : {}),
  }}
  title={!projectId ? 'Save project first' : undefined}
>
  {loading ? (
    <span style={styles.loadingContent}>
      <span style={styles.spinner} />
      PROCESSING...
    </span>
  ) : (
    'RUN PIPELINE'
  )}
</button>
```

- [ ] **Step 3: Pass `currentProjectId` to ProjectForm in App.jsx**

Find `<ProjectForm` in `App.jsx` and add the prop:

```javascript
<ProjectForm
  projectId={currentProjectId}
  {/* ...all existing props unchanged... */}
/>
```

- [ ] **Step 4: Verify in browser**

Load the app — RUN PIPELINE should be grayed out. Save a project — button becomes active. Edit any form field (name, coordinates, description) — `onProjectIdChange(null)` fires and button grays again.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ProjectForm.jsx frontend/src/App.jsx
git commit -m "feat: disable RUN PIPELINE until project is saved"
```

---

### Task 6: Latency Column — Live Timer + Save-Run Body Update

**Files:**
- Modify: `frontend/src/components/ProjectForm.jsx`
- Modify: `frontend/src/components/AgentPipeline.jsx`
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Add state and callbacks to App.jsx**

In `App.jsx`, add two new state variables alongside the existing ones:

```javascript
const [agentDurations, setAgentDurations] = useState({})   // { agent_key: duration_ms }
const [pipelineStartedAt, setPipelineStartedAt] = useState(null)  // ISO string
```

Add two handler functions (near the other handlers):

```javascript
const handleDurationUpdate = (agentKey, durationMs) => {
  setAgentDurations((prev) => ({ ...prev, [agentKey]: durationMs }))
}
const handlePipelineStartedAt = (startedAt) => {
  setPipelineStartedAt(startedAt)
}
```

In the existing place where `agentOutputs` / `agentCosts` are reset when a new run starts (wherever `setPipelineState` is called with all-pending), also reset:

```javascript
setAgentDurations({})
setPipelineStartedAt(null)
```

- [ ] **Step 2: Pass new callbacks to ProjectForm**

```javascript
<ProjectForm
  projectId={currentProjectId}
  onDurationUpdate={handleDurationUpdate}
  onPipelineStartedAt={handlePipelineStartedAt}
  {/* ...all other existing props... */}
/>
```

- [ ] **Step 3: Update ProjectForm to accept and use new props**

Add `onDurationUpdate` and `onPipelineStartedAt` to the function signature:

```javascript
export default function ProjectForm({ onResult, onPipelineUpdate, onStepsUpdate, onLog, onRunningChange, modelSelections, onCostUpdate, onProjectIdChange, onLoadOutputs, onProjectInfoChange, projectId, onDurationUpdate, onPipelineStartedAt }) {
```

In `handleSSEEvent`, update two cases:

```javascript
case 'pipeline_start':
  if (data.pipeline_status) onPipelineUpdate(data.pipeline_status)
  if (data.started_at) onPipelineStartedAt?.(data.started_at)
  break

case 'agent_complete':
  if (data.pipeline_status) onPipelineUpdate(data.pipeline_status)
  if (data.output !== undefined) {
    onStepsUpdate?.((prev) => ({ ...prev, [data.agent]: data.output }))
  }
  if (data.duration_ms != null) {
    onDurationUpdate?.(data.agent, data.duration_ms)
  }
  break
```

- [ ] **Step 4: Update `handleSaveResults` in App.jsx**

Find `handleSaveResults` (around line 140). Update the request body and remove the 409/overwrite handling:

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
    const res = await fetch(`${apiBase}/api/projects/${currentProjectId}/save-run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_outputs: agentOutputs,
        agent_costs: agentCosts,
        agent_durations: agentDurations,
        started_at: pipelineStartedAt,
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

Remove `pendingOverwrite` state declaration and all JSX that references it (the overwrite confirmation dialog).

- [ ] **Step 5: Pass `agentDurations` to AgentPipeline**

Find `<AgentPipeline` in App.jsx and add:

```javascript
<AgentPipeline
  agentDurations={agentDurations}
  {/* ...all existing props unchanged... */}
/>
```

- [ ] **Step 6: Add live timer to AgentPipeline.jsx**

Add `agentDurations = {}` to the function signature:

```javascript
export default function AgentPipeline({
  pipelineState,
  agentOutputs = {},
  selections = {},
  setSelection,
  availableProviders = {},
  modelCatalog = [],
  agentCosts = {},
  agentDurations = {},
})
```

Add timer logic near the top of the component body (after existing state/ref declarations):

```javascript
const startTimesRef = useRef({})
const [, forceUpdate] = useState(0)

useEffect(() => {
  Object.entries(pipelineState).forEach(([key, status]) => {
    if (status === 'running' && !startTimesRef.current[key]) {
      startTimesRef.current[key] = Date.now()
    }
  })
}, [pipelineState])

useEffect(() => {
  const anyRunning = Object.values(pipelineState).some((s) => s === 'running')
  if (!anyRunning) return
  const id = setInterval(() => forceUpdate((n) => n + 1), 100)
  return () => clearInterval(id)
}, [pipelineState])

const getLatencyDisplay = (key) => {
  const status = pipelineState[key]
  if ((status === 'complete' || status === 'error') && agentDurations[key] != null) {
    return (agentDurations[key] / 1000).toFixed(1) + 's'
  }
  if (status === 'running' && startTimesRef.current[key]) {
    return ((Date.now() - startTimesRef.current[key]) / 1000).toFixed(1) + 's'
  }
  return '—'
}
```

Add `useRef` to the React import if not already there:

```javascript
import { useState, useRef, useEffect } from 'react'
```

In the agent row JSX, find where the cost chip is rendered and add a latency chip immediately after it:

```javascript
{/* latency chip — same style as cost chip */}
<span style={{
  ...styles.costChip,
  color: pipelineState[agent.key] === 'complete'
    ? 'var(--green-primary)'
    : pipelineState[agent.key] === 'running'
    ? 'var(--yellow-warn)'
    : 'var(--text-muted)',
}}>
  {getLatencyDisplay(agent.key)}
</span>
```

- [ ] **Step 7: Verify in browser**

Run the pipeline. Each agent row should show a ticking timer while running (e.g. `2.3s`, `2.4s`...) and lock to the final value when the agent completes. After SAVE RESULTS, confirm the browser network tab shows `agent_durations` in the request body.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/AgentPipeline.jsx frontend/src/components/ProjectForm.jsx frontend/src/App.jsx
git commit -m "feat: live latency timer per agent, propagate durations through save-run"
```

---

### Task 7: EVALUATIONS Dropdown Navigation

**Files:**
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Add dropdown state**

```javascript
const [evalMenuOpen, setEvalMenuOpen] = useState(false)
```

- [ ] **Step 2: Replace EVALUATIONS button with dropdown**

Find the EVALUATIONS button (around line 191) and replace it:

```javascript
<div style={{ position: 'relative' }}>
  <button
    style={
      ['evaluations', 'cost', 'latency'].includes(view)
        ? { ...styles.dbBtn, background: 'var(--green-dim)' }
        : styles.dbBtn
    }
    onClick={() => setEvalMenuOpen((o) => !o)}
  >
    EVALUATIONS ▾
  </button>
  {evalMenuOpen && (
    <div
      style={{
        position: 'absolute',
        top: '100%',
        right: 0,
        marginTop: '4px',
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: '4px',
        zIndex: 100,
        minWidth: '160px',
        overflow: 'hidden',
      }}
      onMouseLeave={() => setEvalMenuOpen(false)}
    >
      {[
        { label: 'PIPELINE EVALS', view: 'evaluations' },
        { label: 'COST', view: 'cost' },
        { label: 'LATENCY', view: 'latency' },
      ].map((item) => (
        <button
          key={item.view}
          style={{
            display: 'block',
            width: '100%',
            padding: '8px 14px',
            background: view === item.view ? 'var(--green-dim)' : 'transparent',
            border: 'none',
            borderBottom: '1px solid var(--border)',
            color: 'var(--green-primary)',
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            letterSpacing: '0.05em',
            textAlign: 'left',
            cursor: 'pointer',
          }}
          onClick={() => {
            setView(item.view)
            setEvalMenuOpen(false)
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  )}
</div>
```

- [ ] **Step 3: Add `cost` and `latency` to the view switch**

Find the view-routing JSX (around line 214). Add two new branches before the final `else`:

```javascript
} : view === 'cost' ? (
  <MetricsView metric="cost" onBack={() => setView('main')} />
) : view === 'latency' ? (
  <MetricsView metric="latency" onBack={() => setView('main')} />
) : (
```

- [ ] **Step 4: Add import for MetricsView**

```javascript
import MetricsView from './pages/MetricsView.jsx'
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat: EVALUATIONS dropdown with Pipeline Evals, Cost, and Latency routes"
```

---

### Task 8: MetricsView Component

**Files:**
- Create: `frontend/src/pages/MetricsView.jsx`

- [ ] **Step 1: Create the file**

```javascript
import { useEffect, useRef, useState } from 'react'

const apiBase = import.meta.env.VITE_API_URL ?? ''

const AGENT_ORDER = [
  'project_parser',
  'environmental_data',
  'regulatory_screening',
  'impact_analysis',
  'report_synthesis',
]
const AGENT_LABELS = {
  project_parser: 'PROJECT PARSER',
  environmental_data: 'ENV DATA',
  regulatory_screening: 'REG SCREENING',
  impact_analysis: 'IMPACT ANALYSIS',
  report_synthesis: 'REPORT SYNTH',
}

function formatCost(usd) {
  if (usd == null || usd === 0) return '—'
  if (usd < 0.0001) return '<$0.0001'
  if (usd >= 1) return `$${usd.toFixed(2)}`
  return `$${usd.toFixed(4)}`
}
function formatDuration(ms) {
  if (ms == null || ms === 0) return '—'
  return (ms / 1000).toFixed(1) + 's'
}
function formatTokens(n) {
  if (n == null) return '—'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

function BarChart({ data, formatValue }) {
  if (!data || data.length === 0) {
    return <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>No data yet — run the pipeline and save results.</div>
  }
  const maxVal = Math.max(...data.map((d) => d.value || 0), 0.0001)
  const BAR_W = 48, GAP = 14, CHART_H = 100, LABEL_H = 46
  const totalW = data.length * (BAR_W + GAP)
  return (
    <svg width={totalW} height={CHART_H + LABEL_H} style={{ overflow: 'visible' }}>
      {data.map((d, i) => {
        const val = d.value || 0
        const barH = Math.max((val / maxVal) * CHART_H, 2)
        const x = i * (BAR_W + GAP)
        const y = CHART_H - barH
        const words = AGENT_LABELS[d.agent].split(' ')
        return (
          <g key={d.agent}>
            <rect x={x} y={y} width={BAR_W} height={barH} fill="var(--green-primary)" opacity={0.8} rx={2} />
            <text x={x + BAR_W / 2} y={y - 5} textAnchor="middle" fill="var(--green-primary)" fontSize={9} fontFamily="var(--font-mono)">
              {formatValue(val)}
            </text>
            {words.map((word, wi) => (
              <text key={wi} x={x + BAR_W / 2} y={CHART_H + 14 + wi * 11} textAnchor="middle" fill="var(--text-muted)" fontSize={8} fontFamily="var(--font-mono)">
                {word}
              </text>
            ))}
          </g>
        )
      })}
    </svg>
  )
}

export default function MetricsView({ metric, onBack }) {
  const isCost = metric === 'cost'

  const [overview, setOverview] = useState(null)
  const [runs, setRuns] = useState([])
  const [pricing, setPricing] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedProjectId, setSelectedProjectId] = useState(null)
  const [selectedRunId, setSelectedRunId] = useState(null)
  const [runDetail, setRunDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    Promise.all([
      fetch(`${apiBase}/api/metrics/overview`).then((r) => r.json()),
      fetch(`${apiBase}/api/metrics/runs`).then((r) => r.json()),
      fetch(`${apiBase}/api/metrics/pricing`).then((r) => r.json()),
    ])
      .then(([ov, runsData, pricingData]) => {
        setOverview(ov)
        setRuns(runsData)
        setPricing(pricingData)
        setLoading(false)
      })
      .catch((e) => { setError(e.message); setLoading(false) })
  }, [])

  useEffect(() => {
    if (!selectedRunId) { setRunDetail(null); return }
    setDetailLoading(true)
    fetch(`${apiBase}/api/metrics/runs/${selectedRunId}`)
      .then((r) => r.json())
      .then((d) => { setRunDetail(d); setDetailLoading(false) })
      .catch(() => setDetailLoading(false))
  }, [selectedRunId])

  const chartData = AGENT_ORDER.map((agent) => {
    const entries = (overview?.per_agent || []).filter((a) => a.agent === agent)
    if (!entries.length) return { agent, value: 0 }
    const best = entries.reduce((a, b) => (b.run_count > a.run_count ? b : a))
    return { agent, value: isCost ? best.avg_cost_usd : best.avg_duration_ms }
  })

  const projectOptions = Array.from(
    runs.reduce((map, r) => {
      map.set(r.project_id, r.project_name || `Project ${r.project_id}`)
      return map
    }, new Map())
  ).map(([id, name]) => ({ id, name }))

  const projectRuns = selectedProjectId
    ? runs.filter((r) => r.project_id === selectedProjectId)
    : []

  const s = {
    wrap: { padding: '24px 32px', fontFamily: 'var(--font-mono)', color: 'var(--text)', maxWidth: '1100px', margin: '0 auto' },
    backBtn: { background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-muted)', padding: '4px 10px', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: '11px', letterSpacing: '0.05em', marginBottom: '20px' },
    title: { fontSize: '13px', letterSpacing: '0.12em', color: 'var(--green-primary)', marginBottom: '24px' },
    card: { background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '6px', padding: '20px 24px', marginBottom: '20px' },
    sectionLabel: { fontSize: '10px', letterSpacing: '0.15em', color: 'var(--text-muted)', marginBottom: '16px' },
    statsRow: { display: 'flex', gap: '32px', marginBottom: '24px', flexWrap: 'wrap' },
    statBox: { display: 'flex', flexDirection: 'column', gap: '4px' },
    statValue: { fontSize: '22px', color: 'var(--green-primary)', letterSpacing: '-0.02em' },
    statLabel: { fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.08em' },
    table: { width: '100%', borderCollapse: 'collapse', fontSize: '12px' },
    th: { textAlign: 'left', padding: '6px 10px', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: '10px', letterSpacing: '0.1em' },
    td: { padding: '7px 10px', borderBottom: '1px solid var(--border)', color: 'var(--text)' },
    select: { background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text)', padding: '5px 10px', fontFamily: 'var(--font-mono)', fontSize: '11px', cursor: 'pointer', borderRadius: '3px', marginRight: '10px' },
    muted: { color: 'var(--text-muted)', fontSize: '12px', padding: '12px 0' },
  }

  if (loading) return <div style={s.wrap}><div style={s.muted}>LOADING...</div></div>
  if (error) return <div style={s.wrap}><div style={{ ...s.muted, color: 'var(--red-alert)' }}>ERROR: {error}</div></div>

  const totals = overview?.totals || {}
  const perModel = overview?.per_model || []

  return (
    <div style={s.wrap}>
      <button style={s.backBtn} onClick={onBack}>← BACK</button>
      <div style={s.title}>{isCost ? '// COST ANALYSIS' : '// LATENCY ANALYSIS'}</div>

      {/* Overview */}
      <div style={s.card}>
        <div style={s.sectionLabel}>OVERVIEW — ALL RUNS</div>
        <div style={s.statsRow}>
          <div style={s.statBox}>
            <span style={s.statValue}>
              {isCost ? formatCost(totals.total_cost_usd) : formatDuration(totals.total_duration_ms)}
            </span>
            <span style={s.statLabel}>{isCost ? 'TOTAL COST' : 'TOTAL COMPUTE'}</span>
          </div>
          <div style={s.statBox}>
            <span style={s.statValue}>
              {isCost ? formatCost(totals.avg_cost_per_run) : formatDuration(totals.avg_duration_per_run_ms)}
            </span>
            <span style={s.statLabel}>AVG PER RUN</span>
          </div>
          <div style={s.statBox}>
            <span style={s.statValue}>{totals.total_runs || 0}</span>
            <span style={s.statLabel}>TOTAL RUNS</span>
          </div>
        </div>
        <div style={{ fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '0.1em', marginBottom: '12px' }}>
          AVG {isCost ? 'COST' : 'DURATION'} PER AGENT
        </div>
        <div style={{ overflowX: 'auto', paddingBottom: '8px' }}>
          <BarChart
            data={chartData}
            formatValue={isCost ? formatCost : formatDuration}
          />
        </div>
      </div>

      {/* Model breakdown (cost only) */}
      {isCost && perModel.length > 0 && (
        <div style={s.card}>
          <div style={s.sectionLabel}>MODEL BREAKDOWN</div>
          <table style={s.table}>
            <thead>
              <tr>
                <th style={s.th}>MODEL</th>
                <th style={s.th}>INPUT $/1M</th>
                <th style={s.th}>OUTPUT $/1M</th>
                <th style={s.th}>INPUT TOKENS</th>
                <th style={s.th}>OUTPUT TOKENS</th>
                <th style={s.th}>TOTAL COST</th>
              </tr>
            </thead>
            <tbody>
              {perModel.map((m) => {
                const p = pricing[m.model] || {}
                return (
                  <tr key={m.model}>
                    <td style={s.td}>{p.label || m.model}</td>
                    <td style={s.td}>{p.input_per_1m != null ? `$${p.input_per_1m.toFixed(2)}` : '—'}</td>
                    <td style={s.td}>{p.output_per_1m != null ? `$${p.output_per_1m.toFixed(2)}` : '—'}</td>
                    <td style={s.td}>{formatTokens(m.total_input_tokens)}</td>
                    <td style={s.td}>{formatTokens(m.total_output_tokens)}</td>
                    <td style={{ ...s.td, color: 'var(--green-primary)' }}>{formatCost(m.total_cost_usd)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Run drill-down */}
      <div style={s.card}>
        <div style={s.sectionLabel}>RUN DRILL-DOWN</div>
        <div style={{ marginBottom: '16px' }}>
          <select
            style={s.select}
            value={selectedProjectId ?? ''}
            onChange={(e) => {
              setSelectedProjectId(e.target.value ? Number(e.target.value) : null)
              setSelectedRunId(null)
            }}
          >
            <option value="">— select project —</option>
            {projectOptions.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          {selectedProjectId && (
            <select
              style={s.select}
              value={selectedRunId ?? ''}
              onChange={(e) => setSelectedRunId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">— select run —</option>
              {projectRuns.map((r, i) => (
                <option key={r.id} value={r.id}>
                  Run #{r.id} — {r.started_at
                    ? new Date(r.started_at).toLocaleString()
                    : new Date(r.saved_at || Date.now()).toLocaleString()}
                </option>
              ))}
            </select>
          )}
        </div>

        {detailLoading && <div style={s.muted}>Loading...</div>}
        {!selectedRunId && !detailLoading && (
          <div style={s.muted}>Select a project and run to see the per-agent breakdown.</div>
        )}

        {runDetail && !detailLoading && (
          <>
            <div style={{ marginBottom: '12px', fontSize: '11px', color: 'var(--text-muted)' }}>
              {runDetail.run.project_name} · Total:{' '}
              <span style={{ color: 'var(--green-primary)' }}>
                {isCost ? formatCost(runDetail.run.total_cost_usd) : formatDuration(runDetail.run.total_duration_ms)}
              </span>
            </div>
            <table style={s.table}>
              <thead>
                <tr>
                  <th style={s.th}>AGENT</th>
                  <th style={s.th}>MODEL</th>
                  {isCost ? (
                    <>
                      <th style={s.th}>INPUT</th>
                      <th style={s.th}>OUTPUT</th>
                      <th style={s.th}>COST</th>
                    </>
                  ) : (
                    <th style={s.th}>DURATION</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {AGENT_ORDER.map((key) => {
                  const a = runDetail.agents.find((x) => x.agent === key)
                  return (
                    <tr key={key}>
                      <td style={s.td}>{AGENT_LABELS[key]}</td>
                      <td style={{ ...s.td, color: 'var(--text-muted)' }}>{a?.model || '—'}</td>
                      {isCost ? (
                        <>
                          <td style={s.td}>{a ? formatTokens(a.input_tokens) : '—'}</td>
                          <td style={s.td}>{a ? formatTokens(a.output_tokens) : '—'}</td>
                          <td style={{ ...s.td, color: 'var(--green-primary)' }}>{a ? formatCost(a.cost_usd) : '—'}</td>
                        </>
                      ) : (
                        <td style={{ ...s.td, color: 'var(--green-primary)' }}>{a ? formatDuration(a.duration_ms) : '—'}</td>
                      )}
                    </tr>
                  )
                })}
                <tr style={{ borderTop: '1px solid var(--border)' }}>
                  <td colSpan={2} style={{ ...s.td, color: 'var(--text-muted)', fontSize: '10px', letterSpacing: '0.08em' }}>TOTAL</td>
                  {isCost ? (
                    <>
                      <td style={s.td}>{formatTokens(runDetail.run.total_input_tokens)}</td>
                      <td style={s.td}>{formatTokens(runDetail.run.total_output_tokens)}</td>
                      <td style={{ ...s.td, color: 'var(--green-primary)' }}>{formatCost(runDetail.run.total_cost_usd)}</td>
                    </>
                  ) : (
                    <td style={{ ...s.td, color: 'var(--green-primary)' }}>{formatDuration(runDetail.run.total_duration_ms)}</td>
                  )}
                </tr>
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify both pages in browser**

1. EVALUATIONS → COST: page loads, overview shows empty state message if no data.
2. EVALUATIONS → LATENCY: same layout with latency units.
3. Run pipeline on a saved project → SAVE RESULTS → revisit Cost → confirm bar chart, model table, and run drill-down all populate.
4. Latency page: confirm same run drill-down shows duration_ms in seconds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/MetricsView.jsx
git commit -m "feat: add MetricsView component for Cost and Latency pages"
```

---

### Task 9: Documentation

**Files:**
- Modify: `DATA_MODEL.md`
- Modify: `docs/eval-pipeline.md`
- Modify: `README.md`

- [ ] **Step 1: Update `DATA_MODEL.md` — `pipeline_runs`**

Update the `pipeline_runs` table entry to reflect the new columns and removed UNIQUE constraint:

```
pipeline_runs
  id            SERIAL PK
  project_id    INTEGER FK → projects(id)   [was UNIQUE, now allows many runs per project]
  started_at    TIMESTAMPTZ   nullable — when pipeline began (from SSE pipeline_start event)
  finished_at   TIMESTAMPTZ   nullable — set to NOW() at save time
  total_duration_ms  INTEGER  nullable — sum of all agent duration_ms values
  total_cost_usd     NUMERIC(10,6) nullable — sum of all agent cost_usd values
  total_input_tokens INTEGER  nullable — sum of all agent input_tokens
  total_output_tokens INTEGER nullable — sum of all agent output_tokens
  saved_at      TIMESTAMPTZ   DEFAULT NOW()
```

- [ ] **Step 2: Update `DATA_MODEL.md` — agent output tables**

For each of the 5 agent output tables, add the two new columns and note the dropped UNIQUE:

```
project_parser_outputs (and 4 sibling tables)
  ...existing columns...
  run_id       INTEGER FK → pipeline_runs(id)  nullable — links output to its run
  duration_ms  INTEGER  nullable — milliseconds this agent took
  [UNIQUE (project_id) constraint removed — multiple rows per project now stored]
```

- [ ] **Step 3: Update `docs/eval-pipeline.md`**

Add to the API reference table:

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/api/metrics/overview` | GET | None | Aggregated stats: per-agent avg cost/latency, per-model token totals, overall run totals |
| `/api/metrics/runs` | GET | None | All pipeline runs with project names and aggregate metrics, newest first |
| `/api/metrics/runs/{run_id}` | GET | None | Per-agent breakdown (model, tokens, cost, duration_ms) for one run |
| `/api/metrics/pricing` | GET | None | Model pricing table from `llm/pricing.py` (input/output $/1M tokens) |

Update the SSE event documentation:
- `pipeline_start` now includes `started_at` (ISO 8601 UTC string)
- `agent_complete` now includes `duration_ms` (integer milliseconds)

Update `POST /api/projects/{project_id}/save-run`:
- Now accepts `agent_durations` (object of agent_key → int ms) and `started_at` (ISO string)
- Always creates a new run row; no longer returns 409
- `force` query parameter removed

- [ ] **Step 4: Update `README.md`**

Add to the features / pages section:
- **Cost page** (`EVALUATIONS → COST`): per-agent average cost bar chart, model breakdown table with $/1M token pricing, and run drill-down
- **Latency page** (`EVALUATIONS → LATENCY`): same layout showing agent durations in seconds
- All pipeline runs are now persisted per project; evaluations use the most recent run

- [ ] **Step 5: Commit**

```bash
git add DATA_MODEL.md docs/eval-pipeline.md README.md
git commit -m "docs: update schema, API reference, and README for cost/latency tracking"
```
