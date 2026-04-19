"""Repository for the regulatory_sources table.

Holds the PDF bytes (BYTEA), upload metadata, and live ingestion progress.
The bytes column is intentionally excluded from list queries — only
``get_source_bytes()`` returns it. All access is raw psycopg2 to match
the rest of the project.

Note: CHUNKS_TABLE is hardcoded here (not imported from rag.regulatory.store)
to avoid the transitive pymupdf import that store.py → parser.py → pymupdf
would introduce. The constant value must stay in sync with
``rag.regulatory.store.DEFAULT_TABLE``.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date as _date
from typing import Any, Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger("eia.db.regulatory_sources")

TABLE = "regulatory_sources"

# Matches rag.regulatory.store.DEFAULT_TABLE — kept inline to avoid the
# transitive pymupdf import (store.py imports parser.py which imports pymupdf).
CHUNKS_TABLE = "regulatory_chunks"


_LIST_COLUMNS = """
    id::text,
    filename,
    sha256,
    size_bytes,
    uploaded_at,
    status,
    status_message,
    chunks_total,
    chunks_embedded,
    chunk_count,
    sections_count,
    parser_warnings,
    embedding_dim,
    embedding_started_at,
    embedding_finished_at,
    is_current,
    source_type,
    content_type,
    effective_date,
    cfr_title,
    cfr_part,
    project_id
"""


def init_regulatory_sources_table(conn: Any) -> None:
    """Provision regulatory schema: sources table and ingest audit log.

    Creates (all idempotent):
      * ``regulatory_sources`` with its indexes and the Phase 1 eCFR
        columns (``source_type``, ``content_type``, ``effective_date``,
        ``cfr_title``, ``cfr_part``) plus the partial unique index
        scoped to ``source_type = 'ecfr'``.
      * ``regulatory_ingest_log`` — the audit table that records each
        ingest attempt (trigger, status, duration, chunk counts, errors)
        along with its supporting indexes.

    The function name is retained for backward compatibility even though
    its responsibilities now extend beyond the sources table alone.
    """
    with conn.cursor() as cur:
        cur.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                filename              TEXT        NOT NULL,
                sha256                TEXT        NOT NULL UNIQUE,
                size_bytes            BIGINT      NOT NULL,
                bytes                 BYTEA       NOT NULL,
                uploaded_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                status                TEXT        NOT NULL DEFAULT 'pending',
                status_message        TEXT,
                chunks_total          INT,
                chunks_embedded       INT         NOT NULL DEFAULT 0,
                chunk_count           INT         NOT NULL DEFAULT 0,
                sections_count        INT         NOT NULL DEFAULT 0,
                parser_warnings       INT         NOT NULL DEFAULT 0,
                embedding_dim         INT,
                embedding_started_at  TIMESTAMPTZ,
                embedding_finished_at TIMESTAMPTZ,
                is_current            BOOLEAN     NOT NULL DEFAULT TRUE
            );
            """
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {TABLE}_status_idx ON {TABLE} (status);"
        )

        # ---- Phase 1 eCFR schema additions ----
        cur.execute(f"""
            ALTER TABLE {TABLE}
              ADD COLUMN IF NOT EXISTS source_type    TEXT NOT NULL DEFAULT 'pdf_upload',
              ADD COLUMN IF NOT EXISTS content_type   TEXT NOT NULL DEFAULT 'application/pdf',
              ADD COLUMN IF NOT EXISTS effective_date DATE NULL,
              ADD COLUMN IF NOT EXISTS cfr_title      INT  NULL,
              ADD COLUMN IF NOT EXISTS cfr_part       TEXT NULL;
        """)
        # Partial unique index: only eCFR sources use tuple identity; PDF
        # uploads continue using the sha256 unique constraint.
        cur.execute(f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {TABLE}_identity_idx
              ON {TABLE} (source_type, cfr_title, cfr_part, effective_date)
              WHERE source_type = 'ecfr';
        """)
        # Project assignment — one-to-one: a source belongs to at most one project.
        cur.execute(f"""
            ALTER TABLE {TABLE}
              ADD COLUMN IF NOT EXISTS project_id INTEGER NULL
                REFERENCES projects(id) ON DELETE SET NULL;
        """)
        cur.execute(f"""
            CREATE INDEX IF NOT EXISTS {TABLE}_project_id_idx
              ON {TABLE} (project_id);
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS regulatory_ingest_log (
              id             BIGSERIAL PRIMARY KEY,
              ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              correlation_id TEXT NOT NULL,
              source_id      UUID NULL REFERENCES regulatory_sources(id) ON DELETE SET NULL,
              trigger        TEXT NOT NULL,
              source_type    TEXT NOT NULL,
              cfr_title      INT NULL,
              cfr_part       TEXT NULL,
              effective_date DATE NULL,
              status         TEXT NOT NULL,
              duration_ms    INT NULL,
              chunks_count   INT NULL,
              error_message  TEXT NULL
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS regulatory_ingest_log_ts_idx
              ON regulatory_ingest_log (ts DESC);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS regulatory_ingest_log_source_idx
              ON regulatory_ingest_log (source_id);
        """)
    conn.commit()
    logger.info("Initialized %s", TABLE)


def insert_source(
    conn: Any,
    *,
    filename: str,
    sha256: str,
    size_bytes: int,
    blob: bytes,
    is_current: bool,
) -> dict:
    """Insert a row, or return the existing one if sha256 already exists.

    Race-free: uses ON CONFLICT with a no-op DO UPDATE so that RETURNING
    fires whether we inserted a new row or hit an existing one.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            INSERT INTO {TABLE}
                (filename, sha256, size_bytes, bytes, is_current)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (sha256) DO UPDATE SET sha256 = EXCLUDED.sha256
            RETURNING {_LIST_COLUMNS};
            """,
            (filename, sha256, size_bytes, psycopg2.Binary(blob), is_current),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("insert_source: INSERT ... RETURNING returned no row")
    conn.commit()
    return _normalize(row)


def upsert_ecfr_source(
    conn: Any,
    *,
    cfr_title: int,
    cfr_part: str,
    effective_date: _date | None,
    filename: str,
    bytes_: bytes,
) -> str:
    """Insert or update-in-place keyed on (source_type='ecfr', cfr_title,
    cfr_part, effective_date) via the partial unique index. Returns the
    row's UUID.

    On update, refreshes bytes / sha256 / size_bytes / uploaded_at / status
    while preserving the row id (so cascade_delete_chunks can clear stale
    chunks in-place).

    Note: the ``ON CONFLICT (cols) WHERE source_type = 'ecfr'`` clause
    (inference against a partial unique index) requires PostgreSQL 15+.
    """
    sha = hashlib.sha256(bytes_).hexdigest()
    size = len(bytes_)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO regulatory_sources
              (filename, sha256, size_bytes, bytes,
               source_type, content_type,
               cfr_title, cfr_part, effective_date,
               status, is_current)
            VALUES (%s, %s, %s, %s,
                    'ecfr', 'application/xml',
                    %s, %s, %s,
                    'pending', TRUE)
            ON CONFLICT (source_type, cfr_title, cfr_part, effective_date)
              WHERE source_type = 'ecfr'
              DO UPDATE SET
                filename       = EXCLUDED.filename,
                sha256         = EXCLUDED.sha256,
                size_bytes     = EXCLUDED.size_bytes,
                bytes          = EXCLUDED.bytes,
                uploaded_at    = NOW(),
                status         = 'pending',
                status_message = NULL,
                chunks_total   = NULL,
                chunks_embedded = 0,
                chunk_count    = 0,
                sections_count = 0,
                parser_warnings = 0,
                embedding_dim  = NULL,
                embedding_started_at  = NULL,
                embedding_finished_at = NULL
            RETURNING id
            """,
            (filename, sha, size, psycopg2.Binary(bytes_),
             cfr_title, cfr_part, effective_date),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("upsert_ecfr_source: no id returned")
        return str(row[0])


def find_by_sha256(conn: Any, sha256: str) -> Optional[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_LIST_COLUMNS} FROM {TABLE} WHERE sha256 = %s;",
            (sha256,),
        )
        row = cur.fetchone()
    return _normalize(row) if row else None


def get_source_by_id(conn: Any, source_id: str) -> Optional[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_LIST_COLUMNS} FROM {TABLE} WHERE id = %s;",
            (source_id,),
        )
        row = cur.fetchone()
    return _normalize(row) if row else None


def list_sources(conn: Any) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_LIST_COLUMNS} FROM {TABLE} ORDER BY uploaded_at DESC;"
        )
        rows = cur.fetchall()
    return [_normalize(r) for r in rows]


def get_source_bytes(conn: Any, source_id: str) -> Optional[bytes]:
    """Stream the BYTEA column for one row. Used by the ingest task."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT bytes FROM {TABLE} WHERE id = %s;", (source_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return bytes(row[0])


def update_status(
    conn: Any,
    source_id: str,
    *,
    status: str,
    status_message: Optional[str] = None,
    chunks_total: Optional[int] = None,
    sections_count: Optional[int] = None,
    parser_warnings: Optional[int] = None,
    embedding_dim: Optional[int] = None,
    chunk_count: Optional[int] = None,
    started_at_now: bool = False,
    finished_at_now: bool = False,
) -> None:
    sets: list[str] = ["status = %s"]
    args: list[Any] = [status]
    if status_message is not None:
        sets.append("status_message = %s"); args.append(status_message)
    if chunks_total is not None:
        sets.append("chunks_total = %s"); args.append(chunks_total)
    if sections_count is not None:
        sets.append("sections_count = %s"); args.append(sections_count)
    if parser_warnings is not None:
        sets.append("parser_warnings = %s"); args.append(parser_warnings)
    if embedding_dim is not None:
        sets.append("embedding_dim = %s"); args.append(embedding_dim)
    if chunk_count is not None:
        sets.append("chunk_count = %s"); args.append(chunk_count)
    if started_at_now:
        sets.append("embedding_started_at = NOW()")
    if finished_at_now:
        sets.append("embedding_finished_at = NOW()")
    args.append(source_id)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {TABLE} SET {', '.join(sets)} WHERE id = %s;",
            tuple(args),
        )
    conn.commit()


def update_progress(conn: Any, source_id: str, chunks_embedded: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {TABLE} SET chunks_embedded = %s WHERE id = %s;",
            (chunks_embedded, source_id),
        )
    conn.commit()


def source_exists(conn: Any, source_id: str) -> bool:
    """Return True iff a row with this id exists in regulatory_sources."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM {TABLE} WHERE id = %s;",
            (source_id,),
        )
        return cur.fetchone() is not None


def count_chunks_for_source(conn: Any, source_id: str) -> int:
    """Return the number of chunks belonging to a source."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {CHUNKS_TABLE} WHERE source_id = %s;",
            (source_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(
                "count_chunks_for_source: COUNT(*) returned no row"
            )
        return int(row[0])


def list_chunks_for_source(
    conn: Any,
    source_id: str,
    *,
    limit: int,
    offset: int,
) -> list[dict]:
    """Return a page of chunks for a source, sorted by id.

    Shape matches the /sources/{id}/chunks endpoint contract:
    ``[{id, content, metadata, citation, breadcrumb, token_count}]``.
    The metadata column is defensively coalesced to ``{}`` when NULL so
    callers can always read nested fields safely. The ``bytes`` column is
    never fetched here (see module docstring).
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, content, metadata, (embedding IS NOT NULL) AS embedded
              FROM {CHUNKS_TABLE}
             WHERE source_id = %s
             ORDER BY id
             LIMIT %s OFFSET %s
            """,
            (source_id, limit, offset),
        )
        out: list[dict] = []
        for row in cur.fetchall():
            meta = row[2] or {}
            out.append({
                "id": str(row[0]),
                "content": row[1],
                "metadata": meta,
                "citation": meta.get("citation"),
                "breadcrumb": meta.get("breadcrumb"),
                "token_count": meta.get("token_count"),
                "embedded": bool(row[3]),
            })
        return out


def count_chunks_all(conn: Any) -> int:
    """Return total chunk count across all sources."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {CHUNKS_TABLE};")
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("count_chunks_all: COUNT(*) returned no row")
        return int(row[0])


def list_chunks_all(
    conn: Any,
    *,
    limit: int,
    offset: int,
) -> list[dict]:
    """Return a page of chunks across all sources, sorted by id.

    Shape matches list_chunks_for_source, plus ``source_id``.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, content, metadata, source_id,
                   (embedding IS NOT NULL) AS embedded
              FROM {CHUNKS_TABLE}
             ORDER BY id
             LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        out: list[dict] = []
        for row in cur.fetchall():
            meta = row[2] or {}
            out.append({
                "id": str(row[0]),
                "content": row[1],
                "metadata": meta,
                "citation": meta.get("citation"),
                "breadcrumb": meta.get("breadcrumb"),
                "token_count": meta.get("token_count"),
                "source_id": str(row[3]) if row[3] is not None else None,
                "embedded": bool(row[4]),
            })
        return out


def cascade_delete_chunks(conn: Any, source_id: str) -> int:
    """Delete all chunks belonging to a source. Returns the row count."""
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {CHUNKS_TABLE} WHERE metadata->>'source_id' = %s;",
            (source_id,),
        )
        n = cur.rowcount
    conn.commit()
    return n


def delete_source(conn: Any, source_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {TABLE} WHERE id = %s;", (source_id,))
    conn.commit()


def is_empty(conn: Any) -> bool:
    with conn.cursor() as cur:
        cur.execute(f"SELECT 1 FROM {TABLE} LIMIT 1;")
        return cur.fetchone() is None


def assign_sources_to_project(
    conn: Any,
    source_ids: list[str],
    project_id: int | None,
) -> int:
    """Set project_id on each source in source_ids. Returns rows updated."""
    if not source_ids:
        return 0
    n = 0
    with conn.cursor() as cur:
        for sid in source_ids:
            cur.execute(
                f"UPDATE {TABLE} SET project_id = %s WHERE id = %s::uuid;",
                (project_id, sid),
            )
            n += cur.rowcount
        conn.commit()
    return n


def get_source_ids_for_project(conn: Any, project_id: int) -> list[str]:
    """Return UUIDs of all ready sources assigned to a project."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id::text FROM {TABLE} WHERE project_id = %s AND status = 'ready';",
            (project_id,),
        )
        return [row[0] for row in cur.fetchall()]


def _normalize(row: Optional[dict]) -> Optional[dict]:
    """Convert datetime / UUID values to ISO strings for JSON safety."""
    if row is None:
        return None
    out = dict(row)
    for k in ("uploaded_at", "embedding_started_at", "embedding_finished_at"):
        v = out.get(k)
        if v is not None and hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    return out
