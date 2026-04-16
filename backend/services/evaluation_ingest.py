"""Background ingestion for EIS evaluations: parse → chunk → embed → upsert.

Sibling of services/regulatory_ingest.py. Designed for FastAPI
BackgroundTasks. Opens no connections of its own — the caller must pass
a writable psycopg2 connection.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Callable, Optional

from db.evaluations import (
    get_evaluation_by_id,
    get_evaluation_bytes,
    update_evaluation_progress,
    update_evaluation_status,
)
from rag.embedder_core import detect_embedding_dimension
from rag.evaluation.chunker import EisChunk, chunk_eis_sections, make_chunk_label
from rag.evaluation.parser import parse_eis_pdf
from rag.evaluation.store import (
    build_eis_metadata,
    cascade_delete_chunks_for_evaluation,
    upsert_evaluation_chunks,
)

logger = logging.getLogger("eia.services.evaluation_ingest")

_PROGRESS_MIN_INTERVAL_S = 1.0
_PROGRESS_MIN_DELTA = 5


async def _embed_eis_chunks(
    chunks: list[EisChunk],
    provider: Any,
    concurrency: int = 4,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> list[tuple[str, list[float]]]:
    """Embed each chunk using its section's breadcrumb.

    Returns ``(breadcrumb, vector)`` tuples in the input order.
    """
    sem = asyncio.Semaphore(concurrency)
    total = len(chunks)
    done = 0
    done_lock = asyncio.Lock()
    results: list[Optional[tuple[str, list[float]]]] = [None] * total

    async def _one(i: int, c: EisChunk) -> None:
        nonlocal done
        async with sem:
            text = f"{c.source.breadcrumb}\n\n{c.body}"
            vec = await asyncio.to_thread(provider.embed, text)
            results[i] = (c.source.breadcrumb, vec)
        if on_progress is not None:
            async with done_lock:
                done += 1
                on_progress(done, total)

    await asyncio.gather(*(_one(i, c) for i, c in enumerate(chunks)))
    return [r for r in results if r is not None]


def ingest_evaluation_sync(
    conn: Any,
    *,
    evaluation_id: int,
    embedding_provider: Any,
    correlation_id: Optional[str] = None,
) -> None:
    cid = correlation_id or uuid.uuid4().hex[:8]

    def log(msg, *args):
        logger.info(f"[eval:{cid}] " + msg, *args)

    def warn(msg, *args):
        logger.warning(f"[eval:{cid}] " + msg, *args)

    def err(msg, *args):
        logger.error(f"[eval:{cid}] " + msg, *args)

    try:
        log("ingest start: evaluation_id=%s", evaluation_id)
        update_evaluation_status(conn, evaluation_id, status="embedding",
                                 started_at_now=True)

        row = get_evaluation_by_id(conn, evaluation_id)
        if row is None:
            raise RuntimeError(f"evaluation row not found: {evaluation_id}")
        blob = get_evaluation_bytes(conn, evaluation_id)
        if blob is None:
            raise RuntimeError(f"evaluation bytes missing: {evaluation_id}")

        t0 = time.time()
        sections, parse_warnings = parse_eis_pdf(blob)
        log("parse done: %d sections, %d warnings in %.2fs",
            len(sections), len(parse_warnings), time.time() - t0)

        if not sections:
            warn("zero sections detected — marking failed")
            update_evaluation_status(
                conn, evaluation_id, status="failed",
                status_message=(
                    "No sections detected by EIS parser. "
                    "The PDF may have no numbered headings or be empty."
                ),
            )
            return

        t0 = time.time()
        chunks = chunk_eis_sections(sections)
        log("chunking done: %d chunks in %.2fs",
            len(chunks), time.time() - t0)

        if not chunks:
            warn("sections produced zero chunks — marking failed")
            update_evaluation_status(
                conn, evaluation_id, status="failed",
                status_message="Chunker produced zero chunks from a non-empty section list.",
            )
            return

        dim = detect_embedding_dimension(embedding_provider)
        update_evaluation_status(
            conn, evaluation_id, status="embedding",
            chunks_total=len(chunks), sections_count=len(sections),
            embedding_dim=dim,
        )

        last_write_t = [0.0]
        last_write_n = [0]

        def on_progress(done: int, total: int) -> None:
            now = time.time()
            if (done == total
                or now - last_write_t[0] >= _PROGRESS_MIN_INTERVAL_S
                or done - last_write_n[0] >= _PROGRESS_MIN_DELTA):
                update_evaluation_progress(conn, evaluation_id,
                                           chunks_embedded=done)
                last_write_t[0] = now
                last_write_n[0] = done
                log("embedding progress: %d/%d", done, total)

        t0 = time.time()
        embeddings = asyncio.run(
            _embed_eis_chunks(chunks, embedding_provider,
                              concurrency=4, on_progress=on_progress)
        )
        log("embedding done in %.2fs", time.time() - t0)

        filename = row["filename"]
        sha = row["sha256"]
        rows: list[tuple] = []
        for chunk, (breadcrumb, vec) in zip(chunks, embeddings):
            label = make_chunk_label(
                filename=filename, section=chunk.source,
                chunk_index=chunk.chunk_index,
                total=chunk.total_chunks_in_section,
            )
            meta = build_eis_metadata(
                chunk, breadcrumb=breadcrumb,
                evaluation_id=evaluation_id,
                filename=filename, sha256=sha, chunk_label=label,
            )
            rows.append((chunk, breadcrumb, vec, meta))

        cascade_delete_chunks_for_evaluation(conn, evaluation_id)
        written = upsert_evaluation_chunks(conn, rows,
                                           evaluation_id=evaluation_id)
        log("upserted %d chunks", written)

        update_evaluation_status(
            conn, evaluation_id, status="ready",
            chunks_total=written, finished_at_now=True,
        )
        log("status → ready")

    except Exception as exc:
        err("ingest failed: %s", exc, exc_info=True)
        try:
            conn.rollback()
        except Exception:
            err("rollback raised", exc_info=True)
        try:
            update_evaluation_status(
                conn, evaluation_id, status="failed",
                status_message=f"{type(exc).__name__}: {exc}",
            )
        except Exception:
            err("could not write failure status", exc_info=True)
