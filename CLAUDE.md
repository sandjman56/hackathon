# CLAUDE.md — EIA Agent System Guidelines

## Documentation

**After every implementation, Claude must update documentation by default.**

Specifically, after any code change:
- If a new API endpoint is added: add it to `docs/eval-pipeline.md` API reference table and to `README.md` if user-facing
- If a database table is created or modified: update `DATA_MODEL.md` (schema, relationships, write path, nullable status)
- If a new UI feature is added: update `README.md` and the relevant `docs/` operator guide
- If a new config field or environment variable is added: add it to `README.md`

Do not wait to be asked. Documentation updates are part of every implementation task.

---

## Project Structure

```
backend/
  main.py                    # FastAPI app — all routes
  pipeline.py                # LangGraph streaming pipeline (5 agents)
  db/
    vector_store.py          # init_db(), pgvector store, _get_connection()
    regulatory_sources.py    # Regulatory source tables + ingest
  agents/                    # One file per agent class
  llm/                       # LLM provider abstraction + pricing
  scripts/                   # CLI utilities (e.g. ingest_ecfr)
frontend/
  src/
    components/              # React components (inline CSS, no Tailwind)
    pages/                   # Page-level views
DATA_MODEL.md                # Canonical DB schema reference
README.md                    # Architecture + setup + feature docs
docs/
  eval-pipeline.md           # EIS evaluation + IMPORT RUN operator guide
  ingest-ecfr.md             # eCFR ingest operator guide
```

---

## Key Conventions

- **DB init:** All `CREATE TABLE IF NOT EXISTS` statements go in `db/vector_store.py:init_db()`. No ad-hoc schema creation elsewhere.
- **Backend style:** psycopg2 raw SQL, `_get_connection()` pattern, always `try/finally conn.close()` with `cur` closed in the same `finally`.
- **Frontend style:** Inline CSS style objects with CSS custom properties (`var(--green-primary)`, etc.). No Tailwind, no CSS files.
- **API conventions:** JSON responses, camelCase keys for dates (`savedAt`), snake_case for data fields.
- **Pipeline persistence:** Pass `project_id` in `POST /api/run` to persist agent outputs. The pipeline writes one row per agent to the `*_outputs` tables on completion.

---

## Absolute Rules

- Never modify `render.yaml`
- Never drop or truncate tables
- Cursor lifecycle: always close cursor in `finally`, never rely on early-return paths to close it
- Table name interpolation in SQL: always validate against a frozenset whitelist before interpolating
