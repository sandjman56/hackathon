"""Integration test: ingest → store → search → screening agent.

Exercises the full path that PRs #14-#21 each partially broke:
  build_metadata(is_current=True) → upsert_chunks → search_regulations(is_current=True)

Uses the db_conn fixture (rollback isolation) and stub_embedder (no API calls).
Requires TEST_DATABASE_URL or DATABASE_URL to be set.
"""
from __future__ import annotations

import pytest

from rag.regulatory.chunker import Chunk
from rag.regulatory.parser import DocumentType, RawSection
from rag.regulatory.store import (
    build_metadata,
    init_regulatory_table,
    search_regulations,
    upsert_chunks,
)


def _make_chunk(section_num: str, body: str, part: str = "1500") -> Chunk:
    """Build a minimal Chunk for testing."""
    section = RawSection(
        document_type=DocumentType.CFR_REGULATION,
        section=section_num,
        title=f"Section {section_num}",
        body=body,
        citation=f"40 CFR §{section_num}",
        pages=[1],
        part=part,
        part_title=f"Part {part}",
    )
    return Chunk(
        sources=[section],
        body=body,
        chunk_index=0,
        total_chunks_in_section=1,
        token_count=len(body.split()),
    )


def _ingest_chunks(conn, embedder, chunks_data, is_current=True):
    """Ingest a list of (section_num, body) tuples and return the count."""
    dim = len(embedder.embed("probe"))
    init_regulatory_table(conn, embedding_dim=dim)

    rows = []
    for section_num, body in chunks_data:
        chunk = _make_chunk(section_num, body)
        vec = embedder.embed(f"§{section_num}\n\n{body}")
        breadcrumb = f"40 CFR > Part 1500 > §{section_num}"
        meta = build_metadata(
            chunk,
            breadcrumb,
            source="test_source",
            source_file="test.pdf",
            source_id="test-id-000",
            is_current=is_current,
        )
        rows.append((chunk, breadcrumb, vec, meta))

    return upsert_chunks(conn, rows)


# ---- Tests ----


class TestIngestToSearch:
    """End-to-end: ingest chunks → search with is_current filter."""

    def test_search_returns_chunks_when_is_current_true(self, db_conn, stub_embedder):
        """The happy path that was broken from PR #14 through #21."""
        _ingest_chunks(db_conn, stub_embedder, [
            ("1500.1", "The National Environmental Policy Act applies to all federal agencies."),
            ("1500.2", "Federal agencies shall integrate NEPA requirements early."),
            ("1500.3", "The mandate of NEPA is to protect the environment."),
        ], is_current=True)

        query_vec = stub_embedder.embed("NEPA federal agencies environment")
        results = search_regulations(
            db_conn, query_vec, top_k=5,
            filters={"is_current": True},
        )

        assert len(results) == 3
        assert all(r["metadata"]["is_current"] is True for r in results)
        assert all(r["similarity"] > 0 for r in results)

    def test_search_returns_nothing_when_is_current_false(self, db_conn, stub_embedder):
        """Proves the filter works — chunks marked not-current are excluded."""
        _ingest_chunks(db_conn, stub_embedder, [
            ("1500.1", "The National Environmental Policy Act applies to all federal agencies."),
        ], is_current=False)

        query_vec = stub_embedder.embed("NEPA federal agencies")
        results = search_regulations(
            db_conn, query_vec, top_k=5,
            filters={"is_current": True},
        )

        assert len(results) == 0

    def test_search_without_filter_returns_all(self, db_conn, stub_embedder):
        """Without the is_current filter, all chunks are returned."""
        _ingest_chunks(db_conn, stub_embedder, [
            ("1500.1", "Current regulation text."),
        ], is_current=False)

        query_vec = stub_embedder.embed("regulation")
        results = search_regulations(db_conn, query_vec, top_k=5)

        assert len(results) == 1

    def test_mixed_current_and_historical(self, db_conn, stub_embedder):
        """Multiple corpora: only current chunks returned by default filter."""
        dim = len(stub_embedder.embed("probe"))
        init_regulatory_table(db_conn, embedding_dim=dim)

        # Ingest current corpus
        current_chunk = _make_chunk("1500.1", "Current version of the regulation.")
        current_vec = stub_embedder.embed("current regulation")
        current_meta = build_metadata(
            current_chunk, "40 CFR > §1500.1",
            source="current_corpus", source_file="current.pdf",
            source_id="current-001", is_current=True,
        )

        # Ingest historical corpus
        historical_chunk = _make_chunk("1500.1", "Old superseded version of the regulation.")
        historical_vec = stub_embedder.embed("old regulation")
        historical_meta = build_metadata(
            historical_chunk, "40 CFR > §1500.1 (2005)",
            source="historical_corpus", source_file="historical.pdf",
            source_id="historical-001", is_current=False,
        )
        # Different subsection to avoid dedupe conflict
        historical_meta["subsection"] = "historical"

        upsert_chunks(db_conn, [
            (current_chunk, "40 CFR > §1500.1", current_vec, current_meta),
            (historical_chunk, "40 CFR > §1500.1 (2005)", historical_vec, historical_meta),
        ])

        query_vec = stub_embedder.embed("regulation")
        current_results = search_regulations(
            db_conn, query_vec, top_k=10,
            filters={"is_current": True},
        )
        all_results = search_regulations(db_conn, query_vec, top_k=10)

        assert len(current_results) == 1
        assert current_results[0]["metadata"]["source"] == "current_corpus"
        assert len(all_results) == 2


class TestDimensionMismatchRecovery:
    """init_regulatory_table drops and recreates if dimensions don't match."""

    def test_recreates_table_on_dimension_change(self, db_conn, stub_embedder):
        """Simulates PR #19→#20 scenario: table created at dim=8, then provider changes to dim=4."""
        # Create table with dim=8
        init_regulatory_table(db_conn, embedding_dim=8)

        # Insert a row so we can verify the table is recreated (data lost)
        _ingest_chunks(db_conn, stub_embedder, [
            ("1500.1", "Test chunk at dim 8."),
        ], is_current=True)

        # Now reinitialize with a different dimension (simulates provider change)
        init_regulatory_table(db_conn, embedding_dim=4)

        # Table should exist with new dimension, old data gone
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'regulatory_chunks'::regclass "
                "AND attname = 'embedding'"
            )
            row = cur.fetchone()
            assert row[0] == 4

            cur.execute("SELECT COUNT(*) FROM regulatory_chunks")
            assert cur.fetchone()[0] == 0

    def test_noop_when_dimension_matches(self, db_conn, stub_embedder):
        """If dimensions match, data is preserved."""
        dim = len(stub_embedder.embed("probe"))
        init_regulatory_table(db_conn, embedding_dim=dim)

        _ingest_chunks(db_conn, stub_embedder, [
            ("1500.1", "Should survive reinitialization."),
        ], is_current=True)

        # Reinitialize with same dimension
        init_regulatory_table(db_conn, embedding_dim=dim)

        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM regulatory_chunks")
            assert cur.fetchone()[0] == 1
