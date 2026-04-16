import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse, Response
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from pathlib import Path

import hashlib
import uuid
from typing import Optional

from fastapi import BackgroundTasks, File, Form, UploadFile

from llm.provider_factory import get_embedding_provider
from pipeline import stream_eia_pipeline, cancel_pipeline
from db.vector_store import init_db, _get_connection
from db.regulatory_sources import (
    init_regulatory_sources_table,
    insert_source,
    list_sources,
    get_source_by_id,
    cascade_delete_chunks,
    delete_source,
    source_exists,
    count_chunks_for_source,
    list_chunks_for_source,
)
from services.regulatory_ingest import ingest_source_sync
from services.ecfr_ingest import ingest_ecfr_source
from services.evaluation_ingest import ingest_evaluation_sync
from services.export_report import generate_pdf, generate_latex
from rag.regulatory.store import init_regulatory_table
from rag.regulatory.embedder import detect_embedding_dimension
from db.evaluations import (
    init_evaluations_schema,
    insert_evaluation,
    get_evaluation_by_id,
    list_evaluations as list_evaluations_repo,
    delete_evaluation as delete_evaluation_repo,
    reset_evaluation_for_reingest,
    mark_stuck_evaluations_failed,
)
from rag.evaluation.store import (
    init_evaluation_chunks_table,
    list_chunks_for_evaluation,
    count_chunks_for_evaluation,
    search_evaluation_chunks,
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
    print("[LIFESPAN] Initialising embedding provider\u2026", flush=True, file=sys.stdout)
    try:
        init_db()
        try:
            _conn = _get_connection()
            init_regulatory_sources_table(_conn)
            _conn.close()
        except Exception as exc:
            print(f"[LIFESPAN] regulatory_sources init failed: {exc}",
                  flush=True, file=sys.stdout)
            raise
        emb = get_embedding_provider()
    except Exception as exc:
        print(f"[LIFESPAN] INIT FAILED: {exc}", flush=True, file=sys.stdout)
        raise
    logger.info("Embedding provider: %s", emb.provider_name)
    print(f"[LIFESPAN] Embedding={emb.provider_name}", flush=True, file=sys.stdout)

    app.state.embedding_provider = emb

    # Ensure the regulatory_chunks table exists on every startup.
    try:
        _conn = _get_connection()
        dim = detect_embedding_dimension(emb)
        init_regulatory_table(_conn, embedding_dim=dim)

        # One-time backfill: flip is_current to true for sources/chunks
        # that were ingested before the default was changed.
        with _conn.cursor() as cur:
            cur.execute(
                "UPDATE regulatory_sources SET is_current = true "
                "WHERE is_current = false"
            )
            src_count = cur.rowcount
            cur.execute(
                "UPDATE regulatory_chunks "
                "SET metadata = jsonb_set(metadata, '{is_current}', 'true') "
                "WHERE (metadata->>'is_current')::boolean IS DISTINCT FROM true"
            )
            chunk_count = cur.rowcount
        _conn.commit()
        if src_count or chunk_count:
            print(f"[LIFESPAN] backfill is_current: {src_count} sources, "
                  f"{chunk_count} chunks", flush=True, file=sys.stdout)

        _conn.close()
        print(f"[LIFESPAN] regulatory_chunks table ready (dim={dim})",
              flush=True, file=sys.stdout)
    except Exception as exc:
        print(f"[LIFESPAN] regulatory_chunks init failed: {exc}",
              flush=True, file=sys.stdout)

    # --- evaluations table + evaluation_chunks table + sweep ----------
    try:
        _conn3 = _get_connection()
        init_evaluations_schema(_conn3)
        init_evaluation_chunks_table(_conn3, embedding_dim=dim)
        swept = mark_stuck_evaluations_failed(_conn3)
        if swept:
            print(f"[LIFESPAN] swept {swept} stuck evaluation rows",
                  flush=True, file=sys.stdout)
        _conn3.close()
        print(f"[LIFESPAN] evaluations + evaluation_chunks ready (dim={dim})",
              flush=True, file=sys.stdout)
    except Exception as exc:
        print(f"[LIFESPAN] evaluations init failed: {exc}",
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
    models: dict[str, str] = Field(default_factory=dict)


@app.post("/api/cancel")
def cancel_run():
    cancel_pipeline()
    return {"status": "cancelled"}


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "embedding_provider": app.state.embedding_provider.provider_name,
    }


@app.get("/api/providers")
def get_providers():
    from llm.pricing import MODEL_PRICING, LAST_UPDATED, SOURCES
    from llm.provider_factory import available_providers
    return {
        "available": available_providers(),
        "models": [
            {"id": mid, "label": info["label"], "provider": info["provider"],
             "input": info["input"], "output": info["output"]}
            for mid, info in MODEL_PRICING.items()
        ],
        "pricing_last_updated": LAST_UPDATED,
        "pricing_sources": SOURCES,
    }


@app.post("/api/run")
def run_pipeline(req: RunRequest):
    return StreamingResponse(
        stream_eia_pipeline(
            project_name=req.project_name,
            coordinates=req.coordinates,
            description=req.description,
            models=req.models,
            embedding_provider=app.state.embedding_provider,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/export/pdf")
def export_pdf(data: dict):
    try:
        pdf_bytes = generate_pdf(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=EIA_Report.pdf"},
    )


@app.post("/api/export/latex")
def export_latex(data: dict):
    try:
        tex_str = generate_latex(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(
        content=tex_str.encode("utf-8"),
        media_type="application/x-latex",
        headers={"Content-Disposition": "attachment; filename=EIA_Report.tex"},
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


@app.get("/api/regulations/sources/{source_id}/chunks")
def get_regulatory_source_chunks(
    source_id: str,
    page: int = 1,
    per_page: int = 25,
):
    """Paginated, untruncated chunks for one source, sorted by id."""
    per_page = max(1, min(per_page, 200))
    page = max(1, page)
    offset = (page - 1) * per_page

    cid = _new_correlation_id()
    _sources_logger.info(
        "[sources:%s] chunks list: source_id=%s page=%d per_page=%d",
        cid, source_id, page, per_page,
    )

    conn = _get_connection()
    try:
        if not source_exists(conn, source_id):
            _sources_logger.warning(
                "[sources:%s] chunks list: source_not_found id=%s",
                cid, source_id,
            )
            raise HTTPException(status_code=404, detail="source not found")

        total = count_chunks_for_source(conn, source_id)
        chunks = list_chunks_for_source(
            conn, source_id, limit=per_page, offset=offset,
        )
    finally:
        conn.close()

    total_pages = (total + per_page - 1) // per_page if total else 0
    return {
        "source_id": source_id,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "chunks": chunks,
    }


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
    is_current: bool = Form(True),
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


class EcfrIngestRequest(BaseModel):
    """Request body for POST /api/regulations/sources/ecfr."""
    title: int = Field(
        ..., ge=1, le=50,
        description="CFR title number (1–50). Example: 36 for 36 CFR.",
    )
    part: str = Field(
        ..., min_length=1, max_length=20,
        description="CFR part identifier. String, not int, because parts can have suffixes.",
    )
    date: str | None = Field(
        default="current",
        pattern=r"^(current|\d{4}-\d{2}-\d{2})$",
        description=(
            "Version to fetch. 'current' (default) resolves to the latest valid "
            "amendment date. An ISO date fetches the snapshot from that date."
        ),
    )


def _run_ecfr_ingest_background(
    *, title: int, part: str, date: str, correlation_id: str,
) -> None:
    """Background task entrypoint for POST /api/regulations/sources/ecfr.

    Opens its own DB connection, delegates to the orchestrator, logs any
    exception with stack trace before letting BackgroundTasks swallow it
    (otherwise errors before the orchestrator's first audit write would
    be completely invisible).
    """
    try:
        conn = _get_connection()
    except Exception:
        _sources_logger.exception(
            "[sources:%s] eCFR ingest failed to open DB connection",
            correlation_id,
        )
        return
    try:
        ingest_ecfr_source(
            conn,
            title=title, part=part, date=date,
            embedding_provider=app.state.embedding_provider,
            correlation_id=correlation_id,
            trigger="api",
        )
    except Exception:
        _sources_logger.exception(
            "[sources:%s] eCFR ingest raised in background task",
            correlation_id,
        )
    finally:
        try:
            conn.close()
        except Exception:
            _sources_logger.exception(
                "[sources:%s] conn.close() raised", correlation_id,
            )


@app.post("/api/regulations/sources/ecfr", status_code=202)
async def post_regulatory_source_ecfr(
    req: EcfrIngestRequest,
    background_tasks: BackgroundTasks,
):
    """Kick off eCFR ingest. Fetch + upsert + embed run in background; response is immediate."""
    cid = _new_correlation_id()

    background_tasks.add_task(
        _run_ecfr_ingest_background,
        title=req.title, part=req.part, date=req.date or "current",
        correlation_id=cid,
    )
    return {
        "source_id": None,  # filled in on poll once upsert completes
        "correlation_id": cid,
        "status": "pending",
        "message": (
            f"eCFR ingest started for title {req.title} part {req.part}; "
            f"poll GET /api/regulations/sources and match on cfr_title={req.title}, "
            f"cfr_part='{req.part}' to see status transition to 'ready' or 'failed'."
        ),
    }


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


# --- Evaluations (EIS document uploads) ------------------------------------

def _run_evaluation_ingest_background(evaluation_id: int, correlation_id: str) -> None:
    try:
        conn = _get_connection()
    except Exception:
        _sources_logger.exception(
            "[eval:%s] failed to open DB connection", correlation_id,
        )
        return
    try:
        ingest_evaluation_sync(
            conn,
            evaluation_id=evaluation_id,
            embedding_provider=app.state.embedding_provider,
            correlation_id=correlation_id,
        )
    except Exception:
        _sources_logger.exception(
            "[eval:%s] ingest raised in background task", correlation_id,
        )
    finally:
        try:
            conn.close()
        except Exception:
            _sources_logger.exception(
                "[eval:%s] conn.close() raised", correlation_id,
            )


@app.get("/api/evaluations")
def list_evaluations_endpoint():
    conn = _get_connection()
    try:
        return {"documents": list_evaluations_repo(conn)}
    finally:
        conn.close()


@app.get("/api/evaluations/{eid}")
def get_evaluation_endpoint(eid: int):
    conn = _get_connection()
    try:
        row = get_evaluation_by_id(conn, eid)
        if row is None:
            raise HTTPException(status_code=404, detail="evaluation not found")
        return row
    finally:
        conn.close()


@app.post("/api/evaluations", status_code=201)
async def upload_evaluation(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
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
        row = insert_evaluation(
            conn, filename=fname, sha256=sha,
            size_bytes=len(blob), blob=blob,
        )
        # New row → ingest. Failed dupe → re-queue (retry intent).
        # Ready/embedding/pending dupes → return as-is (no double work).
        should_queue = row["status"] == "pending"
        if row["status"] == "failed":
            should_queue = reset_evaluation_for_reingest(conn, row["id"])
            if should_queue:
                row = get_evaluation_by_id(conn, row["id"]) or row
    finally:
        conn.close()

    if should_queue:
        cid = _new_correlation_id()
        _sources_logger.info(
            "[eval:%s] queueing background ingest for id=%s", cid, row["id"],
        )
        background_tasks.add_task(_run_evaluation_ingest_background,
                                  row["id"], cid)
    return row


@app.post("/api/evaluations/{eid}/reingest", status_code=202)
def reingest_evaluation(eid: int, background_tasks: BackgroundTasks):
    conn = _get_connection()
    try:
        row = get_evaluation_by_id(conn, eid)
        if row is None:
            raise HTTPException(status_code=404, detail="evaluation not found")
        # Single conditional UPDATE — only one parallel caller wins.
        transitioned = reset_evaluation_for_reingest(conn, eid)
    finally:
        conn.close()
    if not transitioned:
        raise HTTPException(
            status_code=409,
            detail=f"cannot reingest while status={row['status']!r}",
        )
    cid = _new_correlation_id()
    background_tasks.add_task(_run_evaluation_ingest_background, eid, cid)
    return {"id": eid, "status": "pending", "correlation_id": cid}


@app.get("/api/evaluations/{eid}/chunks")
def get_evaluation_chunks(eid: int, page: int = 1, per_page: int = 25):
    per_page = max(1, min(per_page, 200))
    page = max(1, page)
    offset = (page - 1) * per_page
    conn = _get_connection()
    try:
        if get_evaluation_by_id(conn, eid) is None:
            raise HTTPException(status_code=404, detail="evaluation not found")
        total = count_chunks_for_evaluation(conn, eid)
        chunks = list_chunks_for_evaluation(conn, eid,
                                            limit=per_page, offset=offset)
    finally:
        conn.close()
    total_pages = (total + per_page - 1) // per_page if total else 0
    return {
        "evaluation_id": eid,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "chunks": chunks,
    }


class EvaluationSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=50)


@app.post("/api/evaluations/{eid}/search")
def search_evaluation(eid: int, req: EvaluationSearchRequest):
    conn = _get_connection()
    try:
        if get_evaluation_by_id(conn, eid) is None:
            raise HTTPException(status_code=404, detail="evaluation not found")
        vec = app.state.embedding_provider.embed(req.query)
        results = search_evaluation_chunks(
            conn, vec, evaluation_id=eid, top_k=req.top_k,
        )
    finally:
        conn.close()
    return {"evaluation_id": eid, "query": req.query, "results": results}


@app.delete("/api/evaluations/{eid}", status_code=204)
def delete_evaluation_endpoint(eid: int):
    conn = _get_connection()
    try:
        row = get_evaluation_by_id(conn, eid)
        if row is None:
            raise HTTPException(status_code=404, detail="evaluation not found")
        # H1 guard: refuse delete while a background task is mid-embed.
        # Cascading the row out from under it would orphan the task and
        # produce FK-violation noise as it tries to write progress/upsert.
        if row["status"] == "embedding":
            raise HTTPException(
                status_code=409,
                detail="cannot delete while ingest is running",
            )
        if delete_evaluation_repo(conn, eid) == 0:
            raise HTTPException(status_code=404, detail="evaluation not found")
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
