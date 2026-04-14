"""Ingest a CFR part via the eCFR API into the regulatory RAG store.

Fetches XML, stages it in regulatory_sources, delegates to the
generalized ingest pipeline. Writes two regulatory_ingest_log rows per
call (one on entry, one on completion).

Public API:
  - ingest_ecfr_source(conn, *, title, part, date, embedding_provider,
                        correlation_id, trigger) -> source_id (str)

Design spec: docs/superpowers/specs/2026-04-14-phase-1-ecfr-pipeline-design.md
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import date as _date
from typing import Any

import httpx

from api_clients.ecfr import fetch_ecfr_xml, resolve_current_date
from db.regulatory_sources import upsert_ecfr_source
from services.regulatory_ingest import ingest_source_sync

logger = logging.getLogger("eia.services.ecfr_ingest")


def _log_audit(
    conn: Any,
    *,
    correlation_id: str,
    source_id: str | None,
    trigger: str,
    cfr_title: int,
    cfr_part: str,
    effective_date: _date | None,
    status: str,
    duration_ms: int | None = None,
    chunks_count: int | None = None,
    error_message: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO regulatory_ingest_log
              (correlation_id, source_id, trigger, source_type,
               cfr_title, cfr_part, effective_date,
               status, duration_ms, chunks_count, error_message)
            VALUES (%s, %s, %s, 'ecfr', %s, %s, %s, %s, %s, %s, %s)
            """,
            (correlation_id, source_id, trigger,
             cfr_title, cfr_part, effective_date,
             status, duration_ms, chunks_count, error_message),
        )
    conn.commit()


def ingest_ecfr_source(
    conn: Any,
    *,
    title: int,
    part: str,
    date: str = "current",
    embedding_provider: Any,
    correlation_id: str | None = None,
    trigger: str = "cli",
) -> str:
    """Fetch eCFR XML, upsert source row, run ingest pipeline.

    Returns the source_id (UUID) of the created or updated source row.

    The connection MUST be writable. Callers invoking this from HTTP
    handlers should pass a fresh connection (NOT the request connection)
    so background work doesn't interfere with request lifecycle. This
    mirrors the contract of ``services.regulatory_ingest.ingest_source_sync``.
    """
    cid = correlation_id or uuid.uuid4().hex[:8]
    t_start = time.time()

    # 1. Resolve date (if "current") via the versions endpoint.
    with httpx.Client() as client:
        if date == "current":
            resolved = resolve_current_date(title=title, client=client, correlation_id=cid)
            logger.info("[cid=%s] resolved current -> %s", cid, resolved)
        else:
            resolved = date

        # 2. Record "started" in audit log before the fetch so a network
        #    failure still leaves a trace.
        effective_date_row: _date | None = None
        if date != "current":
            try:
                effective_date_row = _date.fromisoformat(resolved)
            except ValueError:
                effective_date_row = None

        _log_audit(
            conn, correlation_id=cid, source_id=None, trigger=trigger,
            cfr_title=title, cfr_part=part, effective_date=effective_date_row,
            status="started",
        )

        # 3. Fetch XML.
        try:
            xml_bytes = fetch_ecfr_xml(
                title=title, part=part, date=resolved,
                client=client, correlation_id=cid,
            )
        except Exception as exc:
            # Guard the audit write so a log-table failure doesn't shadow
            # the original fetch exception in the traceback.
            try:
                _log_audit(
                    conn, correlation_id=cid, source_id=None, trigger=trigger,
                    cfr_title=title, cfr_part=part, effective_date=effective_date_row,
                    status="failed",
                    duration_ms=int((time.time() - t_start) * 1000),
                    error_message=f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                logger.exception(
                    "[cid=%s] audit-log write failed after fetch error", cid
                )
            raise

    # 4. Upsert source row.
    filename = f"ecfr_title-{title}_part-{part}_{date}.xml"
    source_id = upsert_ecfr_source(
        conn,
        cfr_title=title, cfr_part=part,
        effective_date=effective_date_row,
        filename=filename,
        bytes_=xml_bytes,
    )
    conn.commit()
    logger.info("[cid=%s] upserted source_id=%s", cid, source_id)

    # 5. Run shared ingest pipeline. (This swallows exceptions internally
    #    and records failures on regulatory_sources.status, so we inspect
    #    the row afterwards to determine the true outcome.)
    ingest_source_sync(
        conn,
        source_id=source_id,
        embedding_provider=embedding_provider,
        correlation_id=cid,
    )

    # 6. Read final source row to determine outcome + chunks_count.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, status_message, chunk_count "
            "FROM regulatory_sources WHERE id=%s",
            (source_id,),
        )
        row = cur.fetchone()
    final_status = row[0] if row else None
    status_message = row[1] if row else None
    chunks_count = int(row[2]) if row and row[2] is not None else None

    # 7. Terminal audit row reflecting the real outcome. Guard the audit
    #    write so a log-table failure doesn't shadow the pipeline result.
    if final_status == "failed":
        try:
            _log_audit(
                conn, correlation_id=cid, source_id=source_id, trigger=trigger,
                cfr_title=title, cfr_part=part, effective_date=effective_date_row,
                status="failed",
                duration_ms=int((time.time() - t_start) * 1000),
                chunks_count=chunks_count,
                error_message=status_message,
            )
        except Exception:
            logger.exception(
                "[cid=%s] audit-log write failed after pipeline failure", cid
            )
    else:
        try:
            _log_audit(
                conn, correlation_id=cid, source_id=source_id, trigger=trigger,
                cfr_title=title, cfr_part=part, effective_date=effective_date_row,
                status="ready",
                duration_ms=int((time.time() - t_start) * 1000),
                chunks_count=chunks_count,
            )
        except Exception:
            logger.exception(
                "[cid=%s] audit-log write failed after pipeline success", cid
            )
    return source_id
