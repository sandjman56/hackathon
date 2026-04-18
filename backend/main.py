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
import psycopg2.extras
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
    count_chunks_all,
    list_chunks_all,
    assign_sources_to_project,
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
    list_evaluations_by_project,
    update_evaluation_project,
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
from db.evaluation_scores import (
    init_evaluation_scores_schema,
    get_ground_truth,
    upsert_ground_truth,
    upsert_score,
    get_score,
)
from rag_eval.extractor import extract_ground_truth
from rag_eval.scorer import compute_scores

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

    # --- evaluation scoring tables -----------------------------------------
    try:
        _conn4 = _get_connection()
        init_evaluation_scores_schema(_conn4)
        _conn4.close()
        print("[LIFESPAN] evaluation_scores tables ready", flush=True, file=sys.stdout)
    except Exception as exc:
        print(f"[LIFESPAN] evaluation_scores init failed: {exc}",
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
    project_id: int | None = None


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
            project_id=req.project_id,
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




class SaveOutputsRequest(BaseModel):
    agent_outputs: dict
    agent_costs: dict = Field(default_factory=dict)


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


AGENT_OUTPUT_TABLES = [
    ("project_parser", "project_parser_outputs"),
    ("environmental_data", "environmental_data_outputs"),
    ("regulatory_screening", "regulatory_screening_outputs"),
    ("impact_analysis", "impact_analysis_outputs"),
    ("report_synthesis", "report_synthesis_outputs"),
]


_ALLOWED_OUTPUT_TABLES = frozenset(t for _, t in AGENT_OUTPUT_TABLES)


@app.get("/api/projects/{project_id}/outputs")
def get_project_outputs(project_id: int):
    conn = _get_connection()
    cur = None
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, coordinates, description, saved_at "
            "FROM projects WHERE id = %s",
            (project_id,),
        )
        proj = cur.fetchone()
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")

        result = {
            "project": {
                "id": proj[0],
                "name": proj[1],
                "coordinates": proj[2],
                "description": proj[3],
                "savedAt": proj[4].isoformat() if proj[4] else None,
            }
        }

        for agent_key, table_name in AGENT_OUTPUT_TABLES:
            assert table_name in _ALLOWED_OUTPUT_TABLES
            cur.execute(
                f'SELECT output, model, input_tokens, output_tokens, cost_usd, saved_at '
                f'FROM "{table_name}" WHERE project_id = %s '
                f'ORDER BY saved_at DESC LIMIT 1',
                (project_id,),
            )
            row = cur.fetchone()
            if row:
                result[agent_key] = {
                    "output": row[0],
                    "model": row[1],
                    "input_tokens": row[2],
                    "output_tokens": row[3],
                    "cost_usd": float(row[4]) if row[4] is not None else None,
                    "savedAt": row[5].isoformat() if row[5] else None,
                }
            else:
                result[agent_key] = None

        return result
    finally:
        if cur is not None:
            cur.close()
        conn.close()


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


class SaveRunRequest(BaseModel):
    agent_outputs: dict
    agent_costs: dict = Field(default_factory=dict)


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


@app.post("/api/projects/{project_id}/outputs")
def save_project_outputs(project_id: int, req: SaveOutputsRequest):
    conn = _get_connection()
    cur = conn.cursor()
    try:
        # Verify project exists
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Project not found. Save the project first.")

        for agent_key, table_name in AGENT_OUTPUT_TABLES:
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


@app.get("/api/projects/{project_id}/outputs")
def load_project_outputs(project_id: int):
    conn = _get_connection()
    cur = conn.cursor()
    try:
        # Verify project exists
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Project not found")

        agent_outputs = {}
        agent_costs = {}
        for agent_key, table_name in AGENT_OUTPUT_TABLES:
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


@app.get("/api/regulations/chunks")
def get_regulatory_chunks_all(page: int = 1, per_page: int = 25):
    """Paginated chunks across all sources, sorted by id."""
    per_page = max(1, min(per_page, 200))
    page = max(1, page)
    offset = (page - 1) * per_page

    conn = _get_connection()
    try:
        total = count_chunks_all(conn)
        chunks = list_chunks_all(conn, limit=per_page, offset=offset)
    finally:
        conn.close()

    total_pages = (total + per_page - 1) // per_page if total else 0
    return {
        "source_id": None,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "chunks": chunks,
    }


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


class AssignSourcesRequest(BaseModel):
    source_ids: list[uuid.UUID]  # Pydantic validates UUID format; rejects malformed strings
    project_id: int | None


@app.patch("/api/regulations/sources/assign")
def assign_regulatory_sources(req: AssignSourcesRequest):
    """Assign (or unassign) a batch of regulatory sources to a project."""
    if not req.source_ids:
        return {"assigned": 0}
    conn = _get_connection()
    try:
        n = assign_sources_to_project(conn, [str(sid) for sid in req.source_ids], req.project_id)
        return {"assigned": n}
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
def list_evaluations_endpoint(project_id: Optional[int] = None):
    conn = _get_connection()
    try:
        if project_id is not None:
            return {"documents": list_evaluations_by_project(conn, project_id)}
        return {"documents": list_evaluations_repo(conn)}
    finally:
        conn.close()


@app.get("/api/evaluations/score/{project_id}")
def get_evaluation_score_by_project(project_id: int):
    """Fetch the saved evaluation score for a project."""
    conn = _get_connection()
    try:
        score = get_score(conn, project_id)
        if score is None:
            raise HTTPException(status_code=404, detail="No score found for this project")
        return score
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
    project_id: int = Form(...),
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
            project_id=project_id,
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


class AssignProjectRequest(BaseModel):
    project_id: Optional[int] = None


@app.patch("/api/evaluations/{eid}/project", status_code=200)
def assign_evaluation_project(eid: int, req: AssignProjectRequest):
    conn = _get_connection()
    try:
        if not update_evaluation_project(conn, eid, req.project_id):
            raise HTTPException(status_code=404, detail="evaluation not found")
        return get_evaluation_by_id(conn, eid)
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
def get_db_table(
    table_name: str,
    page: int = 1,
    per_page: int = 25,
    source_id: str | None = None,
):
    conn = _get_connection()
    try:
        valid_tables = _get_public_tables(conn)
        if table_name not in valid_tables:
            raise HTTPException(status_code=404, detail="Table not found")

        # source_id filter is only meaningful on regulatory_chunks; ignore elsewhere.
        # Treat empty/whitespace source_id as unset — an empty string against a
        # UUID column would raise "invalid input syntax for type uuid" → 500.
        sid = source_id.strip() if isinstance(source_id, str) else None
        apply_source_filter = bool(sid) and table_name == "regulatory_chunks"
        where_sql = ""
        where_params: tuple = ()
        if apply_source_filter:
            where_sql = " WHERE source_id = %s"
            where_params = (sid,)

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

        # Total row count (filtered if applicable)
        cur.execute(f'SELECT COUNT(*) FROM "{table_name}"{where_sql}', where_params)
        total_rows = cur.fetchone()[0]

        # Paginated rows — cast every column to TEXT for JSON safety
        col_names = [c["name"] for c in columns]
        select_exprs = ", ".join(f'"{c}"::text' for c in col_names)
        offset = (page - 1) * per_page
        cur.execute(
            f'SELECT {select_exprs} FROM "{table_name}"{where_sql} LIMIT %s OFFSET %s',
            where_params + (per_page, offset),
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


# --- Evaluation scoring -------------------------------------------------------

class ScoreRequest(BaseModel):
    project_id: int


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


@app.post("/api/evaluations/score")
def score_evaluation(req: ScoreRequest):
    """Trigger evaluation scoring for a project using all linked EIS documents.

    Steps:
    1. Fetch all ready eval docs linked to the project.
    2. Fetch impact_matrix from impact_analysis_outputs for project_id.
    3. Fetch or extract ground truth merged across all linked docs.
    4. Compute Category F1, Significance Accuracy, Semantic Coverage.
    5. Upsert result to evaluation_scores (one row per project) and return it.
    """
    conn = _get_connection()
    try:
        # 1. Find all ready eval docs for this project
        eval_docs = list_evaluations_by_project(conn, req.project_id)
        if not eval_docs:
            raise HTTPException(
                status_code=422,
                detail="No ready EIS documents linked to this project. "
                       "Upload and ingest at least one document assigned to this project.",
            )
        eval_ids = [d["id"] for d in eval_docs]

        # 2. Load impact matrix
        cur = conn.cursor()
        cur.execute(
            "SELECT output FROM impact_analysis_outputs WHERE project_id = %s",
            (req.project_id,),
        )
        row = cur.fetchone()
        cur.close()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail="No impact analysis output found for this project. "
                       "Run the pipeline first.",
            )
        impact_matrix = (row[0] or {}).get("impact_matrix") or row[0] or {}

        # 3. Extract ground truth merged across all linked docs
        from llm.provider_factory import get_llm_provider
        llm = get_llm_provider()

        # Use cached per-doc ground truth where available, re-extract only if missing
        merged_categories: dict[str, dict] = {}
        _SCALE = {"significant": 3, "moderate": 2, "minimal": 1, "none": 0}
        last_model = "none"

        for eid in eval_ids:
            gt_record = get_ground_truth(conn, eid)
            if gt_record is None:
                cats, model_name = extract_ground_truth(conn, eid, llm)
                if cats:
                    upsert_ground_truth(conn, eid, cats, model_name)
                    last_model = model_name
            else:
                cats = gt_record["categories"]
                last_model = gt_record.get("llm_model") or last_model

            for cat in cats:
                name = cat["category_name"]
                existing = merged_categories.get(name)
                if existing is None:
                    merged_categories[name] = cat
                elif _SCALE.get(cat["significance"], 0) > _SCALE.get(existing["significance"], 0):
                    merged_categories[name] = cat

        ground_truth = list(merged_categories.values())
        if not ground_truth:
            raise HTTPException(
                status_code=422,
                detail="Ground truth extraction returned no categories. "
                       "Ensure all linked EIS documents are fully ingested (status=ready).",
            )

        # 4. Compute scores across all linked eval docs
        scores = compute_scores(
            impact_matrix,
            ground_truth,
            conn,
            eval_ids,
            app.state.embedding_provider,
        )

        # 5. Persist and return (one score per project)
        result = upsert_score(conn, req.project_id, scores)
        return result

    finally:
        conn.close()


