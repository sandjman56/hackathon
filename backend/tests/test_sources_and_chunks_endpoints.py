"""GET /api/regulations/sources listing (extended fields) + per-source chunks."""
from __future__ import annotations

import os
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    import main
    class _StubEmbed:
        dim = 8
        provider_name = "stub-embed"
        def embed(self, t): return [0.0] * self.dim
        def embed_batch(self, ts): return [self.embed(t) for t in ts]
    monkeypatch.setattr(main, "get_embedding_provider", lambda: _StubEmbed())
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def seed_source():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    from rag.regulatory.store import init_regulatory_table
    conn = psycopg2.connect(url)
    conn.autocommit = True
    sid = str(uuid.uuid4())
    # Use the production DDL so the test schema mirrors prod exactly
    # (breadcrumb NOT NULL, embedding vector(N) NOT NULL, source_id FK,
    # indexes). Idempotent.
    init_regulatory_table(conn, embedding_dim=8)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO regulatory_sources
              (id, filename, sha256, size_bytes, bytes,
               source_type, content_type, cfr_title, cfr_part,
               effective_date, status, chunk_count, is_current)
            VALUES (%s,%s,%s,%s,%s,'ecfr','application/xml',36,'800',NULL,'ready',3,TRUE)
            """,
            (sid, "title-36_part-800.xml",
             "deadbeef"*8, 100, b"<DIV5/>"),
        )
        for i in range(3):
            cur.execute(
                """
                INSERT INTO regulatory_chunks
                  (content, breadcrumb, embedding, source_id, metadata)
                VALUES (%s, %s, '[0,0,0,0,0,0,0,0]'::vector, %s, %s::jsonb)
                """,
                (f"chunk body {i}", "bc", sid,
                 f'{{"citation":"36 CFR §800.{i}"}}'),
            )
    try:
        yield sid
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM regulatory_chunks WHERE source_id=%s", (sid,))
            cur.execute("DELETE FROM regulatory_sources WHERE id=%s", (sid,))
        conn.close()


def test_list_sources_returns_extended_fields(client, seed_source):
    resp = client.get("/api/regulations/sources")
    assert resp.status_code == 200
    body = resp.json()
    # The endpoint returns {"sources": [...]} — iterate that list.
    matches = [r for r in body["sources"] if r["id"] == seed_source]
    assert matches, f"seeded source {seed_source} not in listing"
    row = matches[0]
    assert row["source_type"] == "ecfr"
    assert row["cfr_title"] == 36
    assert row["cfr_part"] == "800"
    assert row["chunk_count"] == 3


def test_get_chunks_for_source_paginated(client, seed_source):
    resp = client.get(
        f"/api/regulations/sources/{seed_source}/chunks",
        params={"page": 1, "per_page": 25},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_id"] == seed_source
    assert body["page"] == 1
    assert body["per_page"] == 25
    assert body["total"] == 3
    assert len(body["chunks"]) == 3
    c0 = body["chunks"][0]
    assert "content" in c0
    assert "metadata" in c0
    # Untruncated
    assert len(c0["content"]) > 0


def test_get_chunks_for_unknown_source_returns_404(client):
    bogus = str(uuid.uuid4())
    resp = client.get(f"/api/regulations/sources/{bogus}/chunks")
    assert resp.status_code == 404
