import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from pathlib import Path

import hashlib
import uuid
from typing import Optional

from fastapi import BackgroundTasks, File, Form, UploadFile

from llm.provider_factory import get_llm_provider, get_embedding_provider
from pipeline import stream_eia_pipeline, cancel_pipeline
from db.vector_store import init_db, _get_connection
from db.regulatory_sources import (
    init_regulatory_sources_table,
    insert_source,
    list_sources,
    get_source_by_id,
    cascade_delete_chunks,
    delete_source,
)
from services.regulatory_ingest import ingest_source_sync
from rag.regulatory.store import init_regulatory_table
from rag.regulatory.embedder import detect_embedding_dimension

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
        # Initialize the regulatory sources table on every startup.
        try:
            _conn = _get_connection()
            init_regulatory_sources_table(_conn)
            _conn.close()
        except Exception as exc:
            print(f"[LIFESPAN] regulatory_sources init failed: {exc}",
                  flush=True, file=sys.stdout)
            raise
        llm = get_llm_provider()
        emb = get_embedding_provider()
    except Exception as exc:
        print(f"[LIFESPAN] PROVIDER INIT FAILED: {exc}", flush=True, file=sys.stdout)
        raise
    logger.info("LLM provider: %s", llm.provider_name)
    logger.info("Embedding provider: %s", emb.provider_name)
    print(f"[LIFESPAN] LLM={llm.provider_name}  Embedding={emb.provider_name}", flush=True, file=sys.stdout)

    # Dedicated Anthropic provider for regulatory screening (optional)
    screening_llm = None
    if os.environ.get("CLAUDE_KEY"):
        from llm.anthropic_provider import AnthropicProvider
        screening_llm = AnthropicProvider()
        logger.info("Regulatory screening LLM: %s (%s)", screening_llm.provider_name, "haiku")

    app.state.llm_provider = llm
    app.state.embedding_provider = emb
    app.state.screening_llm = screening_llm

    # Ensure the regulatory_chunks table exists on every startup.
    # Without this, the table only gets created during PDF ingestion,
    # so a failed/skipped ingest leaves the screening agent broken.
    try:
        _conn = _get_connection()
        dim = detect_embedding_dimension(emb)
        init_regulatory_table(_conn, embedding_dim=dim)
        _conn.close()
        print(f"[LIFESPAN] regulatory_chunks table ready (dim={dim})",
              flush=True, file=sys.stdout)
    except Exception as exc:
        print(f"[LIFESPAN] regulatory_chunks init failed: {exc}",
              flush=True, file=sys.stdout)

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
            embedding_provider=app.state.embedding_provider,
            screening_llm=app.state.screening_llm,
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


# --- Regulatory sources (DB-backed uploads + ingestion) -------------------

_BACKEND_DIR = Path(__file__).resolve().parent
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB

_sources_logger = logging.getLogger("eia.rag.regulatory.sources")
if not any(isinstance(h, logging.StreamHandler) for h in _sources_logger.handlers):
    _sources_logger.addHandler(_stdout_handler)
_sources_logger.setLevel(logging.DEBUG)
_sources_logger.propagate = False


def _new_correlation_id() -> str:
    return uuid.uuid4().hex[:8]


@app.get("/api/regulations/sources")
def list_regulatory_sources():
    conn = _get_connection()
    try:
        return {"sources": list_sources(conn)}
    finally:
        conn.close()


@app.get("/api/regulations/sources/{source_id}")
def get_regulatory_source(source_id: str):
    conn = _get_connection()
    try:
        row = get_source_by_id(conn, source_id)
        if row is None:
            raise HTTPException(status_code=404, detail="source not found")
        return row
    finally:
        conn.close()


def _run_ingest_background(source_id: str, correlation_id: str):
    """Background task entrypoint. Opens its own DB connection."""
    conn = _get_connection()
    try:
        ingest_source_sync(
            conn,
            source_id=source_id,
            embedding_provider=app.state.embedding_provider,
            correlation_id=correlation_id,
        )
    finally:
        conn.close()


@app.post("/api/regulations/sources", status_code=202)
async def upload_regulatory_source(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    is_current: bool = Form(False),
):
    cid = _new_correlation_id()
    _sources_logger.info(
        "[sources:%s] upload received: filename=%s content_type=%s",
        cid, file.filename, file.content_type,
    )

    if file.content_type not in ("application/pdf", "application/x-pdf", "binary/octet-stream"):
        _sources_logger.warning("[sources:%s] rejected: bad content_type=%s",
                                cid, file.content_type)
        raise HTTPException(status_code=400, detail="file must be application/pdf")

    # Stream-read in chunks with a running size cap so a multi-GB upload
    # can't exhaust disk/memory before the limit check fires.
    buf = bytearray()
    _CHUNK = 1 << 20  # 1 MiB
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
        _sources_logger.warning("[sources:%s] rejected: missing %%PDF magic", cid)
        raise HTTPException(status_code=400, detail="not a valid PDF (missing magic bytes)")

    sha = hashlib.sha256(blob).hexdigest()
    _sources_logger.info("[sources:%s] sha256=%s size=%d", cid, sha[:12], len(blob))

    conn = _get_connection()
    try:
        row = insert_source(
            conn,
            filename=file.filename or "upload.pdf",
            sha256=sha,
            size_bytes=len(blob),
            blob=blob,
            is_current=is_current,
        )
    finally:
        conn.close()

    # If the row already had ready chunks, skip re-ingestion.
    if row["status"] != "ready":
        _sources_logger.info("[sources:%s] queueing background ingest for id=%s",
                             cid, row["id"])
        background_tasks.add_task(_run_ingest_background, row["id"], cid)
    else:
        _sources_logger.info("[sources:%s] dedup hit, already ready, no ingest", cid)

    return row


@app.delete("/api/regulations/sources/{source_id}")
def delete_regulatory_source(source_id: str):
    conn = _get_connection()
    try:
        if get_source_by_id(conn, source_id) is None:
            raise HTTPException(status_code=404, detail="source not found")
        deleted_chunks = cascade_delete_chunks(conn, source_id)
        delete_source(conn, source_id)
        return {"deleted_chunks": deleted_chunks}
    finally:
        conn.close()


# --- Database browser endpoints -------------------------------------------

def _get_public_tables(conn):
    """Return a list of user table names in the public schema."""
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    tables = [row[0] for row in cur.fetchall()]
    cur.close()
    return tables


@app.get("/api/db/tables")
def list_db_tables():
    conn = _get_connection()
    try:
        tables = _get_public_tables(conn)
        cur = conn.cursor()
        result = []
        for table_name in tables:
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s",
                (table_name,),
            )
            col_count = cur.fetchone()[0]
            cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            row_count = cur.fetchone()[0]
            result.append({
                "name": table_name,
                "row_count": row_count,
                "column_count": col_count,
            })
        cur.close()
        return result
    finally:
        conn.close()


@app.get("/api/db/tables/{table_name}")
def get_db_table(table_name: str, page: int = 1, per_page: int = 25):
    conn = _get_connection()
    try:
        valid_tables = _get_public_tables(conn)
        if table_name not in valid_tables:
            raise HTTPException(status_code=404, detail="Table not found")

        cur = conn.cursor()

        # Get columns
        cur.execute(
            "SELECT column_name, data_type "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "ORDER BY ordinal_position",
            (table_name,),
        )
        columns = [{"name": r[0], "type": r[1]} for r in cur.fetchall()]

        # Total row count
        cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        total_rows = cur.fetchone()[0]

        # Paginated rows — cast every column to TEXT for JSON safety
        col_names = [c["name"] for c in columns]
        select_exprs = ", ".join(f'"{c}"::text' for c in col_names)
        offset = (page - 1) * per_page
        cur.execute(
            f'SELECT {select_exprs} FROM "{table_name}" LIMIT %s OFFSET %s',
            (per_page, offset),
        )
        rows = [list(r) for r in cur.fetchall()]

        total_pages = max(1, (total_rows + per_page - 1) // per_page)
        cur.close()

        return {
            "table_name": table_name,
            "columns": columns,
            "rows": rows,
            "total_rows": total_rows,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }
    finally:
        conn.close()


@app.delete("/api/db/tables/{table_name}/rows")
def clear_db_table(table_name: str):
    conn = _get_connection()
    try:
        valid_tables = _get_public_tables(conn)
        if table_name not in valid_tables:
            raise HTTPException(status_code=404, detail="Table not found")

        cur = conn.cursor()
        cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        count = cur.fetchone()[0]
        cur.execute(f'TRUNCATE "{table_name}" CASCADE')
        conn.commit()
        cur.close()
        return {"table_name": table_name, "deleted_count": count}
    finally:
        conn.close()
