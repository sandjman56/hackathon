# Evaluations Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Evaluations tab for uploading, listing, and deleting existing EIS PDF documents.

**Architecture:** Three backend endpoints (list, upload, delete) in `main.py` backed by a new `evaluations` table. A new `EvaluationsView.jsx` component rendered when the header tab is active. The `App.jsx` header gains a third view state.

**Tech Stack:** FastAPI, psycopg2, React, inline styles (matching existing dark theme)

---

### Task 1: Backend — Create evaluations table at startup

**Files:**
- Modify: `backend/main.py:54-108` (lifespan function)

- [ ] **Step 1: Add evaluations table creation in the lifespan function**

In `backend/main.py`, inside the `lifespan` function, add table creation after the `init_regulatory_sources_table` call (after line 63). Insert this block:

```python
        try:
            _conn2 = _get_connection()
            with _conn2.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS evaluations (
                        id SERIAL PRIMARY KEY,
                        filename TEXT NOT NULL,
                        sha256 TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        blob BYTEA NOT NULL,
                        uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
            _conn2.commit()
            _conn2.close()
            print("[LIFESPAN] evaluations table ready", flush=True, file=sys.stdout)
        except Exception as exc:
            print(f"[LIFESPAN] evaluations table init failed: {exc}",
                  flush=True, file=sys.stdout)
```

- [ ] **Step 2: Verify the server starts without errors**

Run: `cd backend && python -c "from main import app; print('OK')"`
Expected: `OK` (no import errors)

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat(db): create evaluations table at startup"
```

---

### Task 2: Backend — Add evaluations CRUD endpoints

**Files:**
- Modify: `backend/main.py` (add 3 endpoints after the existing regulatory source endpoints, before the DB browser section at line 395)

- [ ] **Step 1: Add GET /api/evaluations endpoint**

Add this after the `delete_regulatory_source` endpoint (after line 393) and before the `# --- Database browser endpoints` comment:

```python
# --- Evaluations (EIS document uploads) ------------------------------------

@app.get("/api/evaluations")
def list_evaluations():
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, filename, sha256, size_bytes, uploaded_at "
            "FROM evaluations ORDER BY uploaded_at DESC"
        )
        rows = cur.fetchall()
        cur.close()
        return {
            "documents": [
                {
                    "id": r[0],
                    "filename": r[1],
                    "sha256": r[2],
                    "size_bytes": r[3],
                    "uploaded_at": r[4].isoformat(),
                }
                for r in rows
            ]
        }
    finally:
        conn.close()
```

- [ ] **Step 2: Add POST /api/evaluations endpoint**

Add immediately after the GET endpoint:

```python
@app.post("/api/evaluations", status_code=201)
async def upload_evaluation(file: UploadFile = File(...)):
    if file.content_type not in ("application/pdf", "application/x-pdf", "binary/octet-stream"):
        raise HTTPException(status_code=400, detail="file must be a PDF")

    buf = bytearray()
    _CHUNK = 1 << 20
    while True:
        piece = await file.read(_CHUNK)
        if not piece:
            break
        buf.extend(piece)
        if len(buf) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"file too large (>{_MAX_UPLOAD_BYTES} bytes)",
            )
    blob = bytes(buf)
    if len(blob) == 0:
        raise HTTPException(status_code=400, detail="empty file")
    if not blob.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="not a valid PDF")

    sha = hashlib.sha256(blob).hexdigest()
    fname = file.filename or "upload.pdf"

    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO evaluations (filename, sha256, size_bytes, blob) "
            "VALUES (%s, %s, %s, %s) RETURNING id, uploaded_at",
            (fname, sha, len(blob), blob),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return {
            "id": row[0],
            "filename": fname,
            "sha256": sha,
            "size_bytes": len(blob),
            "uploaded_at": row[1].isoformat(),
        }
    finally:
        conn.close()
```

- [ ] **Step 3: Add DELETE /api/evaluations/{eval_id} endpoint**

Add immediately after the POST endpoint:

```python
@app.delete("/api/evaluations/{eval_id}", status_code=204)
def delete_evaluation(eval_id: int):
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM evaluations WHERE id = %s", (eval_id,))
        if cur.rowcount == 0:
            cur.close()
            raise HTTPException(status_code=404, detail="evaluation not found")
        conn.commit()
        cur.close()
    finally:
        conn.close()
```

- [ ] **Step 4: Verify no import/syntax errors**

Run: `cd backend && python -c "from main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat(api): add evaluations CRUD endpoints"
```

---

### Task 3: Frontend — Create EvaluationsView component

**Files:**
- Create: `frontend/src/components/EvaluationsView.jsx`

- [ ] **Step 1: Create the EvaluationsView component**

Create `frontend/src/components/EvaluationsView.jsx` with the full component. This follows the same layout and styling patterns as `DatabaseView.jsx`:

```jsx
import { useEffect, useState, useRef } from 'react'

const apiBase = import.meta.env.VITE_API_URL ?? ''

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function EvaluationsView({ onBack }) {
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef(null)

  const fetchDocs = async () => {
    try {
      const res = await fetch(`${apiBase}/api/evaluations`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setDocs(data.documents)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDocs()
  }, [])

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(`${apiBase}/api/evaluations`, {
        method: 'POST',
        body: form,
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      const doc = await res.json()
      setDocs((prev) => [doc, ...prev])
    } catch (e) {
      setError(e.message)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const handleDelete = async (id) => {
    try {
      const res = await fetch(`${apiBase}/api/evaluations/${id}`, {
        method: 'DELETE',
      })
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`)
      setDocs((prev) => prev.filter((d) => d.id !== id))
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button style={styles.backBtn} onClick={onBack}>
          &larr; BACK
        </button>
        <span style={styles.pageTitle}>EVALUATIONS</span>
        <span style={styles.docCount}>
          {!loading && !error && `${docs.length} documents`}
        </span>
      </div>

      <div style={styles.body}>
        {/* Upload zone */}
        <div style={styles.uploadZone}>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf"
            onChange={handleUpload}
            style={{ display: 'none' }}
          />
          <button
            style={styles.uploadBtn}
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? 'UPLOADING...' : 'UPLOAD EIS PDF'}
          </button>
          <span style={styles.uploadHint}>PDF files up to 25 MB</span>
        </div>

        {error && (
          <div style={styles.error}>Error: {error}</div>
        )}

        {loading && <div style={styles.muted}>Loading...</div>}

        {!loading && docs.length === 0 && (
          <div style={styles.muted}>No evaluation documents uploaded yet.</div>
        )}

        {!loading && docs.length > 0 && (
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>FILENAME</th>
                <th style={styles.th}>SIZE</th>
                <th style={styles.th}>UPLOADED</th>
                <th style={styles.th}></th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} style={styles.tr}>
                  <td style={styles.td}>{d.filename}</td>
                  <td style={styles.td}>{formatBytes(d.size_bytes)}</td>
                  <td style={styles.td}>
                    {new Date(d.uploaded_at).toLocaleDateString()}
                  </td>
                  <td style={styles.td}>
                    <button
                      style={styles.deleteBtn}
                      onClick={() => handleDelete(d.id)}
                    >
                      DELETE
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

const styles = {
  container: {
    height: '100vh',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  topBar: {
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    padding: '12px 24px',
    borderBottom: '1px solid var(--border)',
    background: 'var(--bg-secondary)',
    flexShrink: 0,
  },
  backBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    letterSpacing: '1px',
    color: 'var(--text-secondary)',
    background: 'transparent',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    padding: '6px 12px',
    cursor: 'pointer',
  },
  pageTitle: {
    fontFamily: 'var(--font-mono)',
    fontSize: '14px',
    fontWeight: 600,
    color: 'var(--green-primary)',
    letterSpacing: '3px',
  },
  docCount: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-muted)',
  },
  body: {
    flex: 1,
    padding: '24px',
    overflowY: 'auto',
  },
  uploadZone: {
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    marginBottom: '24px',
  },
  uploadBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    letterSpacing: '1px',
    color: 'var(--green-primary)',
    background: 'transparent',
    border: '1px solid var(--green-primary)',
    borderRadius: '4px',
    padding: '8px 16px',
    cursor: 'pointer',
  },
  uploadHint: {
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    color: 'var(--text-muted)',
  },
  error: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--red-alert)',
    padding: '8px 0',
  },
  muted: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-muted)',
    fontStyle: 'italic',
    padding: '8px 0',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
  },
  th: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    letterSpacing: '1px',
    color: 'var(--text-muted)',
    textAlign: 'left',
    padding: '8px 12px',
    borderBottom: '1px solid var(--border)',
  },
  tr: {
    borderBottom: '1px solid var(--border)',
  },
  td: {
    fontFamily: 'var(--font-mono)',
    fontSize: '11px',
    color: 'var(--text-secondary)',
    padding: '10px 12px',
  },
  deleteBtn: {
    fontFamily: 'var(--font-mono)',
    fontSize: '9px',
    letterSpacing: '1px',
    color: 'var(--red-alert)',
    background: 'transparent',
    border: '1px solid var(--red-alert)',
    borderRadius: '3px',
    padding: '3px 8px',
    cursor: 'pointer',
  },
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/EvaluationsView.jsx
git commit -m "feat(ui): add EvaluationsView component"
```

---

### Task 4: Frontend — Wire Evaluations tab into App.jsx

**Files:**
- Modify: `frontend/src/App.jsx:1-7` (imports), `frontend/src/App.jsx:72-141` (JSX render)

- [ ] **Step 1: Add EvaluationsView import**

In `frontend/src/App.jsx`, add this import after the `DatabaseView` import (line 6):

```jsx
import EvaluationsView from './components/EvaluationsView.jsx'
```

- [ ] **Step 2: Add EVALUATIONS button to header**

In `App.jsx`, inside the `headerRight` div (line 81), add the evaluations button before the VIEW DB button:

Replace lines 82-86:
```jsx
          <button
            style={styles.dbBtn}
            onClick={() => setView(view === 'db' ? 'main' : 'db')}
          >
            VIEW DB
          </button>
```

With:
```jsx
          <button
            style={view === 'evaluations' ? { ...styles.dbBtn, background: 'var(--green-dim)' } : styles.dbBtn}
            onClick={() => setView(view === 'evaluations' ? 'main' : 'evaluations')}
          >
            EVALUATIONS
          </button>
          <button
            style={view === 'db' ? { ...styles.dbBtn, background: 'var(--green-dim)' } : styles.dbBtn}
            onClick={() => setView(view === 'db' ? 'main' : 'db')}
          >
            VIEW DB
          </button>
```

- [ ] **Step 3: Add EvaluationsView rendering**

Replace the view conditional (lines 92-94):
```jsx
      {view === 'db' ? (
        <DatabaseView onBack={() => setView('main')} />
      ) : (
```

With:
```jsx
      {view === 'db' ? (
        <DatabaseView onBack={() => setView('main')} />
      ) : view === 'evaluations' ? (
        <EvaluationsView onBack={() => setView('main')} />
      ) : (
```

- [ ] **Step 4: Verify frontend compiles**

Run: `cd frontend && npx vite build 2>&1 | tail -5`
Expected: Build succeeds with no errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat(ui): wire Evaluations tab into header and routing"
```

---

### Task 5: Manual smoke test

- [ ] **Step 1: Start backend and frontend**

Run: `cd backend && uvicorn main:app --reload --port 5050 &`
Run: `cd frontend && npm run dev &`

- [ ] **Step 2: Verify in browser**

Open `http://localhost:5173`. Confirm:
1. Header shows three items on the right: `EVALUATIONS`, `VIEW DB`, `SYSTEM ONLINE`
2. Clicking `EVALUATIONS` opens the evaluations page with upload button and empty state message
3. Uploading a PDF shows it in the table
4. Clicking DELETE removes the document
5. Clicking BACK or the `EVALUATIONS` header button returns to the main pipeline view
6. `VIEW DB` still works independently

- [ ] **Step 3: Final commit (if any tweaks needed)**

```bash
git add -A
git commit -m "fix: evaluations tab polish"
```
