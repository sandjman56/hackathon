"""pgvector storage + cosine search for EIS evaluation chunks.

Mirrors rag/regulatory/store.py in shape. Differences:
  * FK column is ``evaluation_id INTEGER REFERENCES evaluations(id)``
    (not UUID — evaluations.id is SERIAL).
  * Dedupe key is ``(evaluation_id, chunk_label)``.
  * Search is always scoped to a single evaluation.

The table name is a module constant (``TABLE``); it is never user-reachable
because we don't accept it as a function parameter. This rules out an entire
class of SQL-injection bugs given the f-string interpolation used below
(including the ``DROP TABLE`` path on dim mismatch).
"""
from __future__ import annotations

import json
import logging
from typing import Any

import psycopg2
import psycopg2.extras

from rag.evaluation.chunker import EisChunk

logger = logging.getLogger("eia.rag.evaluation.store")

TABLE = "evaluation_chunks"


def init_evaluation_chunks_table(conn: Any, embedding_dim: int) -> None:
    """Create the table + indexes if missing. Recreate on dim mismatch.

    On dim mismatch, every row in ``evaluations`` is first marked
    ``status='failed'`` with an actionable message so the UI can't claim
    those uploads are still ``ready`` after their chunks are dropped.
    """
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')

        cur.execute(
            """
            SELECT a.atttypmod FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            WHERE c.relname = %s AND a.attname = 'embedding'
            """,
            (TABLE,),
        )
        row = cur.fetchone()
        if row is not None and row[0] != embedding_dim:
            old_dim = row[0]
            logger.warning(
                "Vector dim mismatch on %s: column=%d provider=%d — "
                "marking every evaluation FAILED then recreating",
                TABLE, old_dim, embedding_dim,
            )
            cur.execute(
                """
                UPDATE evaluations
                   SET status = 'failed',
                       status_message = %s,
                       finished_at = NOW()
                 WHERE status <> 'failed'
                """,
                (
                    f"embedding dim changed from {old_dim} to {embedding_dim}; "
                    "reingest required",
                ),
            )
            cur.execute(f"DROP TABLE {TABLE} CASCADE;")
            conn.commit()

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                evaluation_id INTEGER NOT NULL
                    REFERENCES evaluations(id) ON DELETE CASCADE,
                embedding vector({embedding_dim}),
                content TEXT NOT NULL,
                breadcrumb TEXT NOT NULL,
                chunk_label TEXT NOT NULL,
                metadata JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {TABLE}_dedupe "
            f"ON {TABLE} (evaluation_id, chunk_label);"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {TABLE}_eval_id_idx "
            f"ON {TABLE} (evaluation_id);"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {TABLE}_metadata_gin "
            f"ON {TABLE} USING GIN (metadata jsonb_path_ops);"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {TABLE}_embedding_hnsw "
            f"ON {TABLE} USING hnsw (embedding vector_cosine_ops) "
            f"WITH (m = 16, ef_construction = 64);"
        )
    conn.commit()
    logger.info("Initialized %s with vector(%d)", TABLE, embedding_dim)


def build_eis_metadata(
    chunk: EisChunk,
    breadcrumb: str,
    *,
    evaluation_id: int,
    filename: str,
    sha256: str,
    chunk_label: str,
) -> dict:
    s = chunk.source
    return {
        "evaluation_id": evaluation_id,
        "filename": filename,
        "sha256": sha256,
        "chapter": s.chapter,
        "section_number": s.section_number,
        "section_title": s.section_title,
        "breadcrumb": breadcrumb,
        "chunk_label": chunk_label,
        "page_start": s.page_start,
        "page_end": s.page_end,
        "chunk_index": chunk.chunk_index,
        "total_chunks_in_section": chunk.total_chunks_in_section,
        "token_count": chunk.token_count,
        "has_table": chunk.has_table,
    }


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


_UPSERT_SQL = f"""
    INSERT INTO {TABLE}
        (evaluation_id, embedding, content, breadcrumb, chunk_label, metadata)
    VALUES (%s, %s::vector, %s, %s, %s, %s::jsonb)
    ON CONFLICT (evaluation_id, chunk_label)
    DO UPDATE SET
        embedding = EXCLUDED.embedding,
        content = EXCLUDED.content,
        breadcrumb = EXCLUDED.breadcrumb,
        metadata = EXCLUDED.metadata,
        created_at = NOW();
"""


def _build_payload(
    rows: list[tuple[EisChunk, str, list[float], dict]],
    *,
    evaluation_id: int,
) -> list[tuple]:
    return [
        (
            evaluation_id,
            _vector_literal(emb),
            chunk.body,
            breadcrumb,
            meta["chunk_label"],
            json.dumps(meta),
        )
        for chunk, breadcrumb, emb, meta in rows
    ]


def upsert_evaluation_chunks(
    conn: Any,
    rows: list[tuple[EisChunk, str, list[float], dict]],
    *,
    evaluation_id: int,
) -> int:
    """Insert or replace chunks keyed on ``(evaluation_id, chunk_label)``.

    Additive — does NOT remove rows that aren't in the new payload. Use
    :func:`replace_evaluation_chunks` when you need that.
    """
    if not rows:
        return 0
    payload = _build_payload(rows, evaluation_id=evaluation_id)
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, _UPSERT_SQL, payload, page_size=50)
    conn.commit()
    logger.info("Upserted %d rows into %s for evaluation_id=%d",
                len(payload), TABLE, evaluation_id)
    return len(payload)


def replace_evaluation_chunks(
    conn: Any,
    rows: list[tuple[EisChunk, str, list[float], dict]],
    *,
    evaluation_id: int,
) -> int:
    """Atomically delete every chunk for ``evaluation_id`` and write ``rows``.

    Either the whole replacement commits, or nothing changes and the caller
    sees the original chunk set untouched. Used by the ingest pipeline so a
    failed re-embed doesn't leave the evaluation in a half-empty state.
    """
    payload = _build_payload(rows, evaluation_id=evaluation_id)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {TABLE} WHERE evaluation_id = %s",
                (evaluation_id,),
            )
            if payload:
                psycopg2.extras.execute_batch(cur, _UPSERT_SQL, payload, page_size=50)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    logger.info("Replaced chunks for evaluation_id=%d (%d rows)",
                evaluation_id, len(payload))
    return len(payload)


def cascade_delete_chunks_for_evaluation(conn: Any, evaluation_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {TABLE} WHERE evaluation_id = %s",
            (evaluation_id,),
        )
        count = cur.rowcount
    conn.commit()
    return count


def search_evaluation_chunks(
    conn: Any,
    query_embedding: list[float],
    *,
    evaluation_id: int,
    top_k: int = 5,
) -> list[dict]:
    sql = f"""
        SELECT
            id::text,
            evaluation_id,
            content,
            breadcrumb,
            chunk_label,
            metadata,
            1 - (embedding <=> %s::vector) AS similarity
        FROM {TABLE}
        WHERE evaluation_id = %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """
    vec = _vector_literal(query_embedding)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (vec, evaluation_id, vec, top_k))
        return [dict(r) for r in cur.fetchall()]


def list_chunks_for_evaluation(
    conn: Any, evaluation_id: int, *, limit: int, offset: int,
) -> list[dict]:
    sql = f"""
        SELECT
            id::text,
            chunk_label,
            breadcrumb,
            content,
            metadata,
            (metadata->>'page_start')::int AS page_start,
            (metadata->>'page_end')::int AS page_end
        FROM {TABLE}
        WHERE evaluation_id = %s
        ORDER BY
            COALESCE((metadata->>'chapter')::int, 0),
            metadata->>'section_number',
            (metadata->>'chunk_index')::int
        LIMIT %s OFFSET %s;
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (evaluation_id, limit, offset))
        return [dict(r) for r in cur.fetchall()]


def count_chunks_for_evaluation(conn: Any, evaluation_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE evaluation_id = %s",
            (evaluation_id,),
        )
        r = cur.fetchone()
        return r[0] if r else 0
