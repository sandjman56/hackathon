"""End-to-end ingestion test using the seed PDF + stub embedder."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from db.regulatory_sources import (
    init_regulatory_sources_table,
    insert_source,
    get_source_by_id,
)
from rag.regulatory.store import init_regulatory_table

BACKEND_DIR = Path(__file__).resolve().parent.parent
SEED_PDF = BACKEND_DIR / "NEPA-40CFR1500_1508.pdf"


@pytest.fixture
def initialized(db_conn, stub_embedder):
    init_regulatory_sources_table(db_conn)
    init_regulatory_table(db_conn, embedding_dim=stub_embedder.dim)
    return db_conn, stub_embedder


def test_ingest_seed_pdf_end_to_end(initialized):
    if not SEED_PDF.exists():
        pytest.skip("seed PDF not present")
    conn, embedder = initialized
    raw = SEED_PDF.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    row = insert_source(
        conn, filename=SEED_PDF.name, sha256=sha,
        size_bytes=len(raw), blob=raw, is_current=True,
    )

    from services.regulatory_ingest import ingest_source_sync
    ingest_source_sync(conn, source_id=row["id"], embedding_provider=embedder)

    final = get_source_by_id(conn, row["id"])
    assert final["status"] == "ready"
    assert final["chunk_count"] > 0
    assert final["chunks_embedded"] == final["chunks_total"]
    assert final["embedding_dim"] == embedder.dim


def test_ingest_failed_status_on_zero_sections(initialized):
    conn, embedder = initialized
    junk = b"%PDF-1.4\nthis is not a real pdf body\n%%EOF"
    sha = hashlib.sha256(junk).hexdigest()
    row = insert_source(
        conn, filename="junk.pdf", sha256=sha,
        size_bytes=len(junk), blob=junk, is_current=False,
    )

    from services.regulatory_ingest import ingest_source_sync
    ingest_source_sync(conn, source_id=row["id"], embedding_provider=embedder)

    final = get_source_by_id(conn, row["id"])
    assert final["status"] == "failed"
    assert "no CFR sections" in (final["status_message"] or "").lower() or \
           "parse" in (final["status_message"] or "").lower()
