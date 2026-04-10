"""pgvector storage and similarity retrieval for regulatory chunks.

Uses raw psycopg2 to stay consistent with the rest of the project's DB
layer (`backend/db/vector_store.py` is also psycopg2-based, not SQLAlchemy).

Schema:

.. code-block:: sql

    CREATE TABLE regulatory_chunks (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        embedding   vector(<dim>),       -- dim auto-detected from provider
        content     TEXT      NOT NULL,  -- chunk body WITHOUT breadcrumb
        breadcrumb  TEXT      NOT NULL,  -- the header alone
        metadata    JSONB     NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (
            (metadata->>'citation'),
            (metadata->>'chunk_index'),
            (metadata->>'subsection')
        )
    );

The ``content`` column intentionally stores the raw body so that retrieved
results can be re-rendered with a different breadcrumb format later
without re-ingesting. The breadcrumb is also stored separately so the
caller can show the human-readable hierarchy without re-deriving it.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import psycopg2
import psycopg2.extras

from .chunker import Chunk
from .parser import DocumentType
from .xref import extract_cross_references

logger = logging.getLogger("eia.rag.regulatory.store")

DEFAULT_TABLE = "regulatory_chunks"


# --- DDL ------------------------------------------------------------------

def init_regulatory_table(
    conn: Any,
    embedding_dim: int,
    table_name: str = DEFAULT_TABLE,
) -> None:
    """Create the table, vector index, and JSONB GIN index if missing.

    Idempotent — safe to call on every ingestion run.
    """
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                embedding vector({embedding_dim}),
                content TEXT NOT NULL,
                breadcrumb TEXT NOT NULL,
                metadata JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {table_name}_dedupe_idx
                ON {table_name} (
                    (metadata->>'citation'),
                    (metadata->>'chunk_index'),
                    ((metadata->>'subsection'))
                );
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {table_name}_metadata_gin
                ON {table_name} USING GIN (metadata jsonb_path_ops);
            """
        )
        # HNSW index for cosine similarity. Supports up to 4000 dimensions
        # (IVFFlat caps at 2000, which breaks gemini-embedding-001 at 3072).
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {table_name}_embedding_cosine_idx
                ON {table_name}
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64);
            """
        )
    conn.commit()
    logger.info("Initialized %s with vector(%d)", table_name, embedding_dim)


# --- metadata building ----------------------------------------------------

def build_metadata(
    chunk: Chunk,
    breadcrumb: str,
    *,
    source: str,
    source_file: str,
    source_id: str,
    is_current: bool,
) -> dict:
    """Assemble the per-chunk metadata dict that gets stored as JSONB.

    Args:
        chunk: The chunk being stored.
        breadcrumb: The breadcrumb string already built for this chunk.
        source: Document identifier (e.g. ``"40_CFR_1500-1508"``).
        source_file: Original PDF filename.
        source_id: Foreign key into the regulatory_sources table; lets
            cascade-delete remove all chunks belonging to a source.
        is_current: Whether this corpus is the current authoritative
            version of the regulation. The 2005 reprint is *not* — flag
            it ``False`` so retrieval surfaces the warning to the LLM.
    """
    primary = chunk.sources[0]
    citations = [s.citation for s in chunk.sources]
    cross_refs = extract_cross_references(chunk.body, primary.citation)

    if primary.document_type == DocumentType.CFR_REGULATION:
        document_type = "cfr_regulation"
    elif primary.document_type == DocumentType.STATUTE:
        document_type = "statute"
    elif primary.document_type == DocumentType.EXECUTIVE_ORDER:
        document_type = "executive_order"
    else:
        document_type = "unknown"

    pages = sorted({p for s in chunk.sources for p in s.pages})

    return {
        "source": source,
        "source_file": source_file,
        "source_id": source_id,
        "citation": primary.citation,
        "all_citations": citations,
        "title": primary.title,
        "part": primary.part,
        "part_title": primary.part_title,
        "section": primary.section,
        "subsection": chunk.subsection,
        "chunk_index": chunk.chunk_index,
        "total_chunks_in_section": chunk.total_chunks_in_section,
        "document_type": document_type,
        "agency": "CEQ",
        "statute": primary.parent_statute or "NEPA",
        "statute_title": primary.statute_title,
        "effective_date": primary.effective_date,
        "is_current": is_current,
        "url": "https://www.ecfr.gov/current/title-40/chapter-V/subchapter-A",
        "breadcrumb": breadcrumb,
        "token_count": chunk.token_count,
        "page_numbers": pages,
        "has_table": chunk.has_table,
        "is_definition": chunk.is_definition,
        "is_merged_siblings": chunk.is_merged_siblings,
        "cross_references": cross_refs,
    }


# --- writes ---------------------------------------------------------------

def upsert_chunks(
    conn: Any,
    rows: list[tuple[Chunk, str, list[float], dict]],
    table_name: str = DEFAULT_TABLE,
) -> int:
    """Insert chunks, replacing existing rows that share the dedupe key.

    Args:
        conn: psycopg2 connection.
        rows: Iterable of ``(chunk, breadcrumb, embedding, metadata)``.
        table_name: Target table.

    Returns:
        Number of rows written.
    """
    if not rows:
        return 0
    payload = [
        (
            _vector_literal(emb),
            chunk.body,
            breadcrumb,
            json.dumps(meta),
        )
        for chunk, breadcrumb, emb, meta in rows
    ]
    sql = f"""
        INSERT INTO {table_name} (embedding, content, breadcrumb, metadata)
        VALUES (%s::vector, %s, %s, %s::jsonb)
        ON CONFLICT (
            (metadata->>'citation'),
            (metadata->>'chunk_index'),
            ((metadata->>'subsection'))
        )
        DO UPDATE SET
            embedding  = EXCLUDED.embedding,
            content    = EXCLUDED.content,
            breadcrumb = EXCLUDED.breadcrumb,
            metadata   = EXCLUDED.metadata,
            created_at = NOW();
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, payload, page_size=50)
    conn.commit()
    logger.info("Upserted %d rows into %s", len(payload), table_name)
    return len(payload)


def _vector_literal(vec: list[float]) -> str:
    """Render a Python list as the pgvector input literal: ``[1,2,3]``."""
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


# --- search ---------------------------------------------------------------

def search_regulations(
    conn: Any,
    query_embedding: list[float],
    top_k: int = 5,
    filters: Optional[dict] = None,
    table_name: str = DEFAULT_TABLE,
) -> list[dict]:
    """Cosine-similarity search with optional metadata pre-filtering.

    Args:
        conn: psycopg2 connection.
        query_embedding: The query vector (already produced by the same
            embedding provider used at ingest time — dimensions must match).
        top_k: Number of nearest neighbors to return.
        filters: Optional dict of metadata constraints. Supported keys:
            ``part``, ``document_type``, ``is_definition``, ``statute``,
            ``is_current``. Filters are applied as JSONB predicates *before*
            the vector ordering, so they cut search noise dramatically.
        table_name: Source table.

    Returns:
        A list of result dicts ordered by descending similarity, each
        containing ``id``, ``content``, ``breadcrumb``, ``metadata``,
        and ``similarity`` (in [0, 1]; 1.0 = identical).
    """
    where_sql, where_args = _build_where(filters or {})
    sql = f"""
        SELECT
            id::text,
            content,
            breadcrumb,
            metadata,
            1 - (embedding <=> %s::vector) AS similarity
        FROM {table_name}
        {where_sql}
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """
    vec_literal = _vector_literal(query_embedding)
    args = (vec_literal, *where_args, vec_literal, top_k)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, args)
        return [dict(r) for r in cur.fetchall()]


def _build_where(filters: dict) -> tuple[str, tuple]:
    if not filters:
        return "", ()
    clauses = []
    args: list = []
    for key, value in filters.items():
        if value is None:
            continue
        if key == "is_definition":
            clauses.append("(metadata->>'is_definition')::boolean = %s")
            args.append(bool(value))
        elif key == "is_current":
            clauses.append("(metadata->>'is_current')::boolean = %s")
            args.append(bool(value))
        else:
            clauses.append(f"metadata->>'{_safe_key(key)}' = %s")
            args.append(str(value))
    if not clauses:
        return "", ()
    return "WHERE " + " AND ".join(clauses), tuple(args)


# Whitelist accepted filter keys to keep them out of SQL identifiers.
_ALLOWED_FILTER_KEYS = {
    "part",
    "document_type",
    "statute",
    "section",
    "agency",
    "source",
    "is_current",
    "is_definition",
}


def _safe_key(key: str) -> str:
    if key not in _ALLOWED_FILTER_KEYS:
        raise ValueError(f"unsupported filter key: {key!r}")
    return key
