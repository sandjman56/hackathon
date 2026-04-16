"""Repository for the evaluations table (EIS PDF uploads).

Schema is provisioned idempotently at startup via
``init_evaluations_schema`` — includes the legacy columns plus the new
status/progress columns added for the EIS ingest pipeline.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger("eia.db.evaluations")


_LIST_COLUMNS = """
    id, filename, sha256, size_bytes, uploaded_at,
    status, status_message, chunks_total, chunks_embedded,
    sections_count, embedding_dim, started_at, finished_at
"""


def init_evaluations_schema(conn: Any) -> None:
    """Create the table if missing and add any new columns idempotently."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                id SERIAL PRIMARY KEY,
                filename TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                blob BYTEA NOT NULL,
                uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        cur.execute("""
            ALTER TABLE evaluations
              ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending',
              ADD COLUMN IF NOT EXISTS status_message TEXT,
              ADD COLUMN IF NOT EXISTS chunks_total INTEGER NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS chunks_embedded INTEGER NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS sections_count INTEGER NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS embedding_dim INTEGER,
              ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
              ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS evaluations_sha256_idx
              ON evaluations (sha256)
        """)
    conn.commit()


def _row_to_dict(r) -> dict:
    d = dict(r)
    for k in ("uploaded_at", "started_at", "finished_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


def insert_evaluation(
    conn: Any, *, filename: str, sha256: str, size_bytes: int, blob: bytes,
) -> dict:
    """Insert a new evaluation row or return the existing row on sha256 hit."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT {_LIST_COLUMNS}
            FROM evaluations WHERE sha256 = %s
            """,
            (sha256,),
        )
        existing = cur.fetchone()
        if existing:
            return _row_to_dict(existing)

        cur.execute(
            f"""
            INSERT INTO evaluations (filename, sha256, size_bytes, blob)
            VALUES (%s, %s, %s, %s)
            RETURNING {_LIST_COLUMNS}
            """,
            (filename, sha256, size_bytes, psycopg2.Binary(blob)),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("insert_evaluation: INSERT...RETURNING returned no row")
    conn.commit()
    return _row_to_dict(row)


def get_evaluation_by_id(conn: Any, eid: int) -> Optional[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_LIST_COLUMNS} FROM evaluations WHERE id = %s",
            (eid,),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_evaluation_by_sha(conn: Any, sha256: str) -> Optional[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_LIST_COLUMNS} FROM evaluations WHERE sha256 = %s",
            (sha256,),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_evaluation_bytes(conn: Any, eid: int) -> Optional[bytes]:
    with conn.cursor() as cur:
        cur.execute("SELECT blob FROM evaluations WHERE id = %s", (eid,))
        r = cur.fetchone()
    if r is None:
        return None
    b = r[0]
    return bytes(b) if b is not None else None


def list_evaluations(conn: Any) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_LIST_COLUMNS} FROM evaluations ORDER BY uploaded_at DESC"
        )
        return [_row_to_dict(r) for r in cur.fetchall()]


def delete_evaluation(conn: Any, eid: int) -> int:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM evaluations WHERE id = %s", (eid,))
        count = cur.rowcount
    conn.commit()
    return count


def update_evaluation_status(
    conn: Any,
    eid: int,
    *,
    status: str,
    status_message: Optional[str] = None,
    chunks_total: Optional[int] = None,
    sections_count: Optional[int] = None,
    embedding_dim: Optional[int] = None,
    started_at_now: bool = False,
    finished_at_now: bool = False,
    chunks_embedded: Optional[int] = None,
) -> None:
    sets = ["status = %s"]
    args: list[Any] = [status]
    if status_message is not None:
        sets.append("status_message = %s")
        args.append(status_message)
    elif status in ("pending", "embedding", "ready"):
        sets.append("status_message = NULL")
    if chunks_total is not None:
        sets.append("chunks_total = %s")
        args.append(chunks_total)
    if chunks_embedded is not None:
        sets.append("chunks_embedded = %s")
        args.append(chunks_embedded)
    if sections_count is not None:
        sets.append("sections_count = %s")
        args.append(sections_count)
    if embedding_dim is not None:
        sets.append("embedding_dim = %s")
        args.append(embedding_dim)
    if started_at_now:
        sets.append("started_at = NOW()")
    if finished_at_now:
        sets.append("finished_at = NOW()")
    args.append(eid)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE evaluations SET {', '.join(sets)} WHERE id = %s",
            args,
        )
    conn.commit()


def update_evaluation_progress(conn: Any, eid: int, *, chunks_embedded: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE evaluations SET chunks_embedded = %s WHERE id = %s",
            (chunks_embedded, eid),
        )
    conn.commit()


def reset_evaluation_for_reingest(conn: Any, eid: int) -> bool:
    """Atomically transition an evaluation to ``status='pending'``.

    Only succeeds when the current status is ``ready`` or ``failed`` —
    rows in ``pending`` or ``embedding`` are left untouched. Returns
    ``True`` when a row transitioned (caller should queue the background
    task) and ``False`` otherwise (caller should return 409).

    The conditional update closes the TOCTOU window between SELECT and
    RESET that would otherwise let two parallel reingest requests both
    queue a background task for the same evaluation.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluations
               SET status = 'pending',
                   status_message = NULL,
                   chunks_total = 0,
                   chunks_embedded = 0,
                   sections_count = 0,
                   started_at = NULL,
                   finished_at = NULL
             WHERE id = %s
               AND status IN ('ready', 'failed')
            """,
            (eid,),
        )
        transitioned = cur.rowcount == 1
    conn.commit()
    return transitioned


def mark_stuck_evaluations_failed(conn: Any) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluations
               SET status = 'failed',
                   status_message = 'interrupted by restart'
             WHERE status IN ('pending', 'embedding')
            """,
        )
        count = cur.rowcount
    conn.commit()
    return count
