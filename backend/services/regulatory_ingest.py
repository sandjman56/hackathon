"""Background ingestion: parse → chunk → embed → upsert.

Designed to be invoked from FastAPI BackgroundTasks. Synchronous wrapper
for tests, async-friendly internals so embedding can fan out via the
existing embedder helper.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

import pymupdf

from db.regulatory_sources import (
    cascade_delete_chunks,
    get_source_bytes,
    update_progress,
    update_status,
)
from rag.regulatory.chunker import chunk_sections
from rag.regulatory.embedder import detect_embedding_dimension, embed_chunks
from rag.regulatory.parser import parse_pdf
from rag.regulatory.parser_pa_code import parse_pa_code_pdf
from rag.regulatory.store import (
    build_metadata,
    init_regulatory_table,
    upsert_chunks,
)

logger = logging.getLogger("eia.rag.regulatory.sources")

# Throttle progress writes so we don't hammer the DB on small chunks.
_PROGRESS_MIN_INTERVAL_S = 1.0
_PROGRESS_MIN_DELTA = 5


def detect_parser(blob: bytes, *, content_type: str) -> str:
    """Route bytes to the right parser based on content_type.

    EXTENSION POINT: add new content_type branches here.
    Pattern: see parser_ecfr.py for the XML reference implementation.
    See docs/ingest-ecfr.md 'Adding a new source type' for the procedure.

    Returns:
        ``"ecfr_xml"`` for eCFR Versioner XML responses,
        ``"pa_code"`` for Pennsylvania Code browser-printed PDFs,
        ``"federal"`` for NEPA/CFR-style scanned PDF reprints.
    """
    if content_type == "application/xml":
        return "ecfr_xml"

    if content_type == "application/pdf":
        try:
            doc = pymupdf.open(stream=blob, filetype="pdf")
            first_page_text = doc[0].get_text("text") if len(doc) > 0 else ""
            doc.close()
        except Exception:
            return "federal"
        if "Pennsylvania Code" in first_page_text:
            return "pa_code"
        return "federal"

    raise ValueError(f"unsupported content_type: {content_type!r}")


def ingest_source_sync(
    conn: Any,
    *,
    source_id: str,
    embedding_provider: Any,
    correlation_id: str | None = None,
) -> None:
    """Run ingestion synchronously against an open psycopg2 connection.

    The connection MUST be writable. The HTTP layer should pass a fresh
    connection (NOT the request connection) so background work doesn't
    interfere with request lifecycle.
    """
    cid = correlation_id or uuid.uuid4().hex[:8]
    log = lambda msg, *args: logger.info(f"[sources:{cid}] " + msg, *args)
    warn = lambda msg, *args: logger.warning(f"[sources:{cid}] " + msg, *args)
    err = lambda msg, *args: logger.error(f"[sources:{cid}] " + msg, *args)

    try:
        log("ingest start: source_id=%s", source_id)
        update_status(conn, source_id, status="embedding",
                      started_at_now=True)

        blob = get_source_bytes(conn, source_id)
        if blob is None:
            raise RuntimeError(f"source row not found: {source_id}")

        parser_type = detect_parser(blob)
        log("detected parser: %s, %d bytes", parser_type, len(blob))
        t0 = time.time()
        if parser_type == "pa_code":
            sections, parser_warnings = parse_pa_code_pdf(blob)
        else:
            sections, parser_warnings = parse_pdf(blob)
        log("parse done: %d sections, %d warnings in %.2fs",
            len(sections), len(parser_warnings), time.time() - t0)

        if not sections:
            warn("zero sections detected — marking failed")
            update_status(
                conn, source_id, status="failed",
                status_message=(
                    f"No sections detected by {parser_type} parser. "
                    "The PDF may not match any supported regulatory format."
                ),
            )
            return

        log("chunking begin")
        t0 = time.time()
        chunks = chunk_sections(sections)
        log("chunking done: %d chunks in %.2fs", len(chunks), time.time() - t0)

        if not chunks:
            warn("sections produced zero chunks — marking failed")
            update_status(
                conn, source_id, status="failed",
                status_message="Chunker produced zero chunks from a non-empty section list.",
            )
            return

        dim = detect_embedding_dimension(embedding_provider)
        log("embedding dim=%d  chunks_total=%d", dim, len(chunks))
        update_status(
            conn, source_id, status="embedding",
            chunks_total=len(chunks),
            sections_count=len(sections),
            parser_warnings=len(parser_warnings),
            embedding_dim=dim,
        )

        # Throttled progress callback
        last_write_t = [0.0]
        last_write_n = [0]

        def on_progress(done: int, total: int) -> None:
            now = time.time()
            if (
                done == total
                or now - last_write_t[0] >= _PROGRESS_MIN_INTERVAL_S
                or done - last_write_n[0] >= _PROGRESS_MIN_DELTA
            ):
                update_progress(conn, source_id, chunks_embedded=done)
                last_write_t[0] = now
                last_write_n[0] = done
                log("embedding progress: %d/%d", done, total)

        log("embedding begin")
        t0 = time.time()
        embeddings = asyncio.run(
            embed_chunks(chunks, embedding_provider, concurrency=4,
                         on_progress=on_progress)
        )
        log("embedding done in %.2fs", time.time() - t0)

        # Build rows + upsert
        init_regulatory_table(conn, embedding_dim=dim)
        from db.regulatory_sources import get_source_by_id
        row = get_source_by_id(conn, source_id)
        if row is None:
            raise RuntimeError(f"row vanished mid-ingest: {source_id}")
        rows = []
        for chunk, (breadcrumb, vec) in zip(chunks, embeddings):
            meta = build_metadata(
                chunk,
                breadcrumb,
                source=row["filename"].rsplit(".", 1)[0],
                source_file=row["filename"],
                source_id=source_id,
                is_current=row["is_current"],
            )
            rows.append((chunk, breadcrumb, vec, meta))

        # Idempotent re-embed: clear old chunks for this source first
        cascade_delete_chunks(conn, source_id)
        written = upsert_chunks(conn, rows)
        log("upserted %d chunks", written)

        update_status(
            conn, source_id, status="ready",
            chunk_count=written, finished_at_now=True,
        )
        log("status → ready")

    except Exception as exc:
        err("ingest failed: %s", exc, exc_info=True)
        try:
            conn.rollback()
        except Exception:
            err("rollback before failure write also raised", exc_info=True)
        try:
            update_status(
                conn, source_id, status="failed",
                status_message=f"{type(exc).__name__}: {exc}",
            )
        except Exception:
            err("could not even write failure status", exc_info=True)
        # Do not re-raise — background task swallows exceptions silently
        # and we've recorded the state in the row.
