# EIA Multi-Agent System

Automated Environmental Impact Assessment (EIA) screening tool powered by a multi-agent pipeline. Upload a project description and location, and the system queries federal environmental databases, screens NEPA regulations via RAG, and produces a structured impact report.

## Architecture

```
                         +------------------+
                         |   React Frontend |
                         |   (Vite + Render)|
                         +--------+---------+
                                  |
                              POST /api/run
                                  |
                         +--------v---------+
                         |  FastAPI Backend  |
                         +--------+---------+
                                  |
                      +-----------v-----------+
                      |   LangGraph Pipeline  |
                      +-----------+-----------+
                                  |
          +-----------+-----------+-----------+-----------+
          |           |           |           |           |
  +-------v--+ +-----v------+ +-v--------+ +v--------+ +v-----------+
  | Project  | | Environ.   | | Regulatory| | Impact  | | Report     |
  | Parser   | | Data Agent | | Screening | | Analysis| | Synthesis  |
  +----------+ +-----+------+ +----+------+ +----+----+ +------------+
                     |              |
              Federal REST    RAG over NEPA
              APIs (USFWS,    guidance docs
              NWI, FEMA,      (LlamaIndex +
              Farmland,        pgvector)
              EJScreen)
```

### 5-Agent Pipeline

```
[1] PROJECT PARSER ──> [2] ENVIRONMENTAL DATA ──> [3] REGULATORY SCREENING
                                                            │
                        [5] REPORT SYNTHESIS <── [4] IMPACT ANALYSIS
```

1. **Project Parser** — Extracts structured project metadata from natural language
2. **Environmental Data** — Queries 5 federal REST APIs by coordinates
3. **Regulatory Screening** — RAG retrieval over NEPA guidance to find applicable regulations
4. **Impact Analysis** — Populates significance matrix across impact categories
5. **Report Synthesis** — Generates final screening-level EIA document

## Tech Stack

- **Frontend:** React (Vite)
- **Backend:** FastAPI (Python)
- **Database:** PostgreSQL + pgvector
- **Agent Orchestration:** LangGraph
- **RAG:** LlamaIndex with pgvector store
- **LLM Providers:** OpenAI, Anthropic, Ollama (switchable)

## Local Development

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy and fill in environment variables
cp ../.env.example ../.env

# Run the server
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` requests to `http://localhost:8000`.

### Database

Ensure PostgreSQL is running with pgvector installed:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Set `DATABASE_URL` in `.env` to your connection string:
```
DATABASE_URL=postgresql://user:password@localhost:5432/eia_db
```

### Regulatory Source Ingestion

The regulatory RAG store ingests:

- **PDF uploads** via `POST /api/regulations/sources` (multipart upload) — federal CFR/statute PDFs and Pennsylvania Code PDFs
- **eCFR XML** via `POST /api/regulations/sources/ecfr` or `cd backend && python -m scripts.ingest_ecfr` — live CFR parts fetched from the eCFR Versioner API

See [`docs/ingest-ecfr.md`](docs/ingest-ecfr.md) for the eCFR ingest operator guide.

### EIS Evaluation Ingestion

EIS documents uploaded on the Evaluations page are automatically parsed,
chunked, embedded, and stored in the `evaluation_chunks` table for
scoped retrieval.

- Upload via the Evaluations page, or `POST /api/evaluations`
- Query via `POST /api/evaluations/{id}/search`

See [`docs/eval-pipeline.md`](docs/eval-pipeline.md) for the operator guide.

### Evaluation Panel — IMPORT RUN

The lower half of the Evaluations page is a resizable split pane for reviewing past pipeline runs:

- **IMPORT RUN** (left panel) — pick any saved project from a dropdown; loads the latest agent output from each of the 5 output tables and displays them in collapsible sections with model/token/cost metadata.
- **EVALUATE** (right panel) — stub button for future scoring/comparison logic.

The split divider is draggable (15%–85% range). Agent outputs are rendered with type-aware views: key-value pairs (Project Parser), API cards (Environmental Data), regulation cards (Regulatory Screening), significance matrix table (Impact Analysis), and sectioned report (Report Synthesis).

**Requires `project_id` to be passed on the run request** so pipeline outputs are persisted to the database. The `POST /api/run` body accepts an optional `project_id: int` field. Without it, IMPORT RUN will show `null` for all agents.

**API:** `GET /api/projects/{id}/outputs` — returns the project record and the latest output row for each of the 5 agents.

## Switching LLM Providers

Change two environment variables — no code changes needed:

```bash
# Use OpenAI (default)
LLM_PROVIDER=openai
EMBEDDING_PROVIDER=openai

# Use Anthropic for LLM + OpenAI for embeddings
LLM_PROVIDER=anthropic
EMBEDDING_PROVIDER=openai

# Fully offline with Ollama
LLM_PROVIDER=ollama
EMBEDDING_PROVIDER=ollama
```

> **Note:** Anthropic does not offer an embedding API. Use `openai` or `ollama` for `EMBEDDING_PROVIDER`.

## Render Deployment

1. Push this repo to GitHub
2. Create a new **Blueprint** on Render and connect the repo
3. Render reads `render.yaml` and provisions:
   - `eia-backend` — Python web service (FastAPI)
   - `eia-frontend` — Static site (React/Vite)
   - `eia-db` — Managed PostgreSQL
4. Set secret environment variables (`OPENAI_API_KEY`, etc.) in the Render dashboard
5. After the database is created, connect and run `CREATE EXTENSION IF NOT EXISTS vector;`


## License

Copyright (c) 2025 sandjman56. All rights reserved.

This project is proprietary software. Personal and educational use is permitted.
**Sale, commercial licensing, or monetization of this software or any derivative work is strictly prohibited without the express prior written consent of the repository owner.**

See [LICENSE](./LICENSE) for full terms.
