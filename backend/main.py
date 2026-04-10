import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from pathlib import Path

from llm.provider_factory import get_llm_provider, get_embedding_provider
from pipeline import stream_eia_pipeline, cancel_pipeline
from db.vector_store import init_db, _get_connection
from rag.regulatory.parser import parse_pdf
from rag.regulatory.chunker import chunk_sections
from rag.regulatory.embedder import detect_embedding_dimension, embed_chunks
from rag.regulatory.store import (
    DEFAULT_TABLE,
    build_metadata,
    init_regulatory_table,
    upsert_chunks,
)

load_dotenv()

# Explicit stdout handler on the eia logger so it survives Uvicorn's dictConfig
# override and is always visible in Render/container logs.
_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setLevel(logging.DEBUG)
_stdout_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s")
)
_eia_logger = logging.getLogger("eia")
_eia_logger.setLevel(logging.DEBUG)
_eia_logger.addHandler(_stdout_handler)
_eia_logger.propagate = False  # prevent double-printing via root logger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eia")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[LIFESPAN] Initialising LLM providers…", flush=True, file=sys.stdout)
    try:
        init_db()
        llm = get_llm_provider()
        emb = get_embedding_provider()
    except Exception as exc:
        print(f"[LIFESPAN] PROVIDER INIT FAILED: {exc}", flush=True, file=sys.stdout)
        raise
    logger.info("LLM provider: %s", llm.provider_name)
    logger.info("Embedding provider: %s", emb.provider_name)
    print(f"[LIFESPAN] LLM={llm.provider_name}  Embedding={emb.provider_name}", flush=True, file=sys.stdout)
    app.state.llm_provider = llm
    app.state.embedding_provider = emb
    yield


app = FastAPI(title="EIA Multi-Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    project_name: str
    coordinates: str
    description: str


@app.post("/api/cancel")
def cancel_run():
    cancel_pipeline()
    return {"status": "cancelled"}


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_provider": app.state.llm_provider.provider_name,
        "embedding_provider": app.state.embedding_provider.provider_name,
    }


@app.post("/api/run")
def run_pipeline(req: RunRequest):
    return StreamingResponse(
        stream_eia_pipeline(
            project_name=req.project_name,
            coordinates=req.coordinates,
            description=req.description,
            llm=app.state.llm_provider,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


class SaveProjectRequest(BaseModel):
    name: str
    coordinates: str
    description: str


@app.get("/api/projects")
def list_projects():
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, coordinates, description, saved_at FROM projects ORDER BY saved_at DESC"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "id": r[0],
            "name": r[1],
            "coordinates": r[2],
            "description": r[3],
            "savedAt": r[4].isoformat(),
        }
        for r in rows
    ]


@app.post("/api/projects", status_code=201)
def save_project(req: SaveProjectRequest):
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO projects (name, coordinates, description) VALUES (%s, %s, %s) RETURNING id, saved_at",
        (req.name, req.coordinates, req.description),
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return {
        "id": row[0],
        "name": req.name,
        "coordinates": req.coordinates,
        "description": req.description,
        "savedAt": row[1].isoformat(),
    }


@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: int):
    conn = _get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
    if cur.rowcount == 0:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Project not found")
    conn.commit()
    cur.close()
    conn.close()


# --- Regulatory sources (PDF discovery + ingestion) ----------------------

_BACKEND_DIR = Path(__file__).resolve().parent


def _ingested_counts_by_source_file() -> dict[str, int]:
    """Return {source_file: chunk_count} from the regulatory_chunks table."""
    try:
        conn = _get_connection()
    except Exception as exc:
        logger.warning("ingested_counts: DB unavailable: %s", exc)
        return {}
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT to_regclass('public.{DEFAULT_TABLE}')"
        )
        if cur.fetchone()[0] is None:
            return {}
        cur.execute(
            f"""
            SELECT metadata->>'source_file' AS source_file, COUNT(*)
            FROM {DEFAULT_TABLE}
            GROUP BY metadata->>'source_file'
            """
        )
        return {row[0]: int(row[1]) for row in cur.fetchall() if row[0]}
    finally:
        conn.close()


@app.get("/api/regulations/sources")
def list_regulatory_sources():
    """List PDFs found in the backend directory and their ingestion status."""
    pdfs = sorted(_BACKEND_DIR.glob("*.pdf"))
    counts = _ingested_counts_by_source_file()
    out = []
    for p in pdfs:
        stat = p.stat()
        out.append({
            "filename": p.name,
            "size_bytes": stat.st_size,
            "ingested_chunks": counts.get(p.name, 0),
        })
    return {"sources": out}


class IngestRequest(BaseModel):
    filename: str
    is_current: bool = False


@app.post("/api/regulations/ingest")
def ingest_regulatory_pdf(req: IngestRequest):
    """Parse, chunk, embed, and upsert one PDF into regulatory_chunks."""
    pdf_path = (_BACKEND_DIR / req.filename).resolve()
    # Confine to backend dir.
    if _BACKEND_DIR not in pdf_path.parents or not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    if pdf_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Not a PDF file")

    logger.info("[ingest] parsing %s", pdf_path.name)
    sections, parser_warnings = parse_pdf(str(pdf_path))
    chunks = chunk_sections(sections)
    logger.info(
        "[ingest] %s -> %d sections, %d chunks, %d warnings",
        pdf_path.name, len(sections), len(chunks), len(parser_warnings),
    )

    provider = app.state.embedding_provider
    dim = detect_embedding_dimension(provider)

    import asyncio as _asyncio
    embeddings = _asyncio.run(embed_chunks(chunks, provider, concurrency=4))

    conn = _get_connection()
    try:
        init_regulatory_table(conn, embedding_dim=dim)
        rows = []
        for chunk, (breadcrumb, vec) in zip(chunks, embeddings):
            meta = build_metadata(
                chunk,
                breadcrumb,
                source=pdf_path.stem,
                source_file=pdf_path.name,
                source_id="",                # Task 7 will replace this endpoint
                is_current=req.is_current,
            )
            rows.append((chunk, breadcrumb, vec, meta))
        written = upsert_chunks(conn, rows)
    finally:
        conn.close()

    return {
        "filename": pdf_path.name,
        "sections": len(sections),
        "chunks_written": written,
        "parser_warnings": len(parser_warnings),
        "embedding_dim": dim,
    }
