"""pgvector storage + cosine search for EIS evaluation chunks.

Mirrors rag/regulatory/store.py in shape. Differences:
  * FK column is ``evaluation_id INTEGER REFERENCES evaluations(id)``
    (not UUID — evaluations.id is SERIAL).
  * Dedupe key is ``(evaluation_id, chunk_label)``.
  * Search is always scoped to a single evaluation.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import psycopg2
import psycopg2.extras

from rag.evaluation.chunker import EisChunk

logger = logging.getLogger("eia.rag.evaluation.store")

DEFAULT_TABLE = "evaluation_chunks"


def init_evaluation_chunks_table(
    conn: Any,
    embedding_dim: int,
    table_name: str = DEFAULT_TABLE,
) -> None:
    """Create the table + indexes if missing. Recreate on dim mismatch."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')

        cur.execute(
            """
            SELECT a.atttypmod FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            WHERE c.relname = %s AND a.attname = 'embedding'
            """,
            (table_name,),
        )
        row = cur.fetchone()
        if row is not None and row[0] != embedding_dim:
            logger.warning(
                "Vector dim mismatch on %s: column=%d provider=%d — recreating",
                table_name, row[0], embedding_dim,
            )
            cur.execute(f"DROP TABLE {table_name} CASCADE;")
            conn.commit()

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
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
            f"CREATE UNIQUE INDEX IF NOT EXISTS {table_name}_dedupe "
            f"ON {table_name} (evaluation_id, chunk_label);"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {table_name}_eval_id_idx "
            f"ON {table_name} (evaluation_id);"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {table_name}_metadata_gin "
            f"ON {table_name} USING GIN (metadata jsonb_path_ops);"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {table_name}_embedding_hnsw "
            f"ON {table_name} USING hnsw (embedding vector_cosine_ops) "
            f"WITH (m = 16, ef_construction = 64);"
        )
    conn.commit()
    logger.info("Initialized %s with vector(%d)", table_name, embedding_dim)


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


def upsert_evaluation_chunks(
    conn: Any,
    rows: list[tuple[EisChunk, str, list[float], dict]],
    *,
    evaluation_id: int,
    table_name: str = DEFAULT_TABLE,
) -> int:
    """Insert or replace chunks keyed on ``(evaluation_id, chunk_label)``."""
    if not rows:
        return 0
    payload = [
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
    sql = f"""
        INSERT INTO {table_name}
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
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, payload, page_size=50)
    conn.commit()
    logger.info("Upserted %d rows into %s for evaluation_id=%d",
                len(payload), table_name, evaluation_id)
    return len(payload)


def cascade_delete_chunks_for_evaluation(
    conn: Any, evaluation_id: int, table_name: str = DEFAULT_TABLE,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {table_name} WHERE evaluation_id = %s",
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
    table_name: str = DEFAULT_TABLE,
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
        FROM {table_name}
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
    table_name: str = DEFAULT_TABLE,
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
        FROM {table_name}
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


def count_chunks_for_evaluation(
    conn: Any, evaluation_id: int, table_name: str = DEFAULT_TABLE,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {table_name} WHERE evaluation_id = %s",
            (evaluation_id,),
        )
        return cur.fetchone()[0]
