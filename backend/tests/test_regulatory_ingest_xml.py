"""Full pipeline: fixture XML → chunker → (stub embedder) → DB.

Uses the existing db_conn fixture + a stub embedding provider so no network.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

import psycopg2
import pytest

from db.regulatory_sources import TABLE as SOURCES_TABLE  # noqa: F401
from db.vector_store import init_db
from services.regulatory_ingest import ingest_source_sync

_FIXTURES = Path(__file__).parent / "fixtures" / "ecfr"


class _StubEmbedder:
    model_name = "stub-embedding-8"
    dim = 8
    def embed(self, text: str) -> list[float]:
        return [0.1] * self.dim
    def embed_batch(self, texts):
        return [self.embed(t) for t in texts]


@pytest.fixture
def embedding_provider():
    return _StubEmbedder()


@pytest.fixture
def real_conn():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    try:
        init_db()
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _stage_xml_source(conn, xml_bytes: bytes) -> str:
    """Insert a fake 'ecfr' row directly and return its id."""
    source_id = str(uuid.uuid4())
    sha = hashlib.sha256(xml_bytes).hexdigest()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO regulatory_sources
              (id, filename, sha256, size_bytes, bytes,
               source_type, content_type, cfr_title, cfr_part,
               effective_date, is_current)
            VALUES (%s, %s, %s, %s, %s, 'ecfr', 'application/xml',
                    36, '800', NULL, TRUE)
            """,
            (source_id, "title-36_part-800.xml", sha, len(xml_bytes), xml_bytes),
        )
    conn.commit()
    return source_id


def test_ingest_xml_writes_chunks_with_typed_source_id(real_conn, embedding_provider):
    xml = (_FIXTURES / "title-36_part-800.xml").read_bytes()
    source_id = _stage_xml_source(real_conn, xml)

    ingest_source_sync(
        real_conn,
        source_id=source_id,
        embedding_provider=embedding_provider,
        correlation_id="test1234",
    )

    with real_conn.cursor() as cur:
        cur.execute("SELECT status, chunk_count FROM regulatory_sources WHERE id=%s",
                    (source_id,))
        status, chunk_count = cur.fetchone()
    assert status == "ready"
    assert chunk_count > 0

    with real_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM regulatory_chunks WHERE source_id=%s",
                    (source_id,))
        (typed_count,) = cur.fetchone()
    assert typed_count == chunk_count, "typed source_id FK must be populated"
