"""Repository tests for the regulatory_sources table.

These tests open a real psycopg2 connection (via the db_conn fixture in
conftest.py) and roll back at the end of every test, so nothing
persists. Set TEST_DATABASE_URL to point at a scratch database.
"""
from __future__ import annotations

import hashlib

import pytest

from db.regulatory_sources import (
    cascade_delete_chunks,
    delete_source,
    find_by_sha256,
    get_source_bytes,
    init_regulatory_sources_table,
    insert_source,
    list_sources,
    update_progress,
    update_status,
)


@pytest.fixture
def initialized_db(db_conn):
    init_regulatory_sources_table(db_conn)
    return db_conn


def _bytes(payload: str = "FAKE PDF") -> bytes:
    return payload.encode()


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class TestInsertAndDedup:
    def test_insert_returns_row(self, initialized_db):
        b = _bytes("hello")
        row = insert_source(
            initialized_db,
            filename="t.pdf",
            sha256=_sha(b),
            size_bytes=len(b),
            blob=b,
            is_current=False,
        )
        assert row["filename"] == "t.pdf"
        assert row["status"] == "pending"
        assert "id" in row

    def test_insert_dedupes_by_sha256(self, initialized_db):
        b = _bytes("dup")
        row1 = insert_source(
            initialized_db, filename="a.pdf", sha256=_sha(b),
            size_bytes=len(b), blob=b, is_current=False,
        )
        row2 = insert_source(
            initialized_db, filename="b.pdf", sha256=_sha(b),
            size_bytes=len(b), blob=b, is_current=False,
        )
        assert row1["id"] == row2["id"]

    def test_find_by_sha256(self, initialized_db):
        b = _bytes("findme")
        row = insert_source(
            initialized_db, filename="t.pdf", sha256=_sha(b),
            size_bytes=len(b), blob=b, is_current=False,
        )
        found = find_by_sha256(initialized_db, _sha(b))
        assert found is not None
        assert found["id"] == row["id"]

        missing = find_by_sha256(initialized_db, "0" * 64)
        assert missing is None


class TestListExcludesBytes:
    def test_list_does_not_return_bytes(self, initialized_db):
        b = _bytes("listme")
        insert_source(
            initialized_db, filename="t.pdf", sha256=_sha(b),
            size_bytes=len(b), blob=b, is_current=False,
        )
        rows = list_sources(initialized_db)
        assert len(rows) == 1
        assert "bytes" not in rows[0]


class TestProgressAndStatus:
    def test_update_progress_persists(self, initialized_db):
        b = _bytes("p")
        row = insert_source(
            initialized_db, filename="t.pdf", sha256=_sha(b),
            size_bytes=len(b), blob=b, is_current=False,
        )
        update_status(initialized_db, row["id"], status="embedding",
                      chunks_total=100)
        update_progress(initialized_db, row["id"], chunks_embedded=42)
        rows = list_sources(initialized_db)
        assert rows[0]["chunks_embedded"] == 42
        assert rows[0]["chunks_total"] == 100
        assert rows[0]["status"] == "embedding"

    def test_update_status_to_failed(self, initialized_db):
        b = _bytes("f")
        row = insert_source(
            initialized_db, filename="t.pdf", sha256=_sha(b),
            size_bytes=len(b), blob=b, is_current=False,
        )
        update_status(initialized_db, row["id"], status="failed",
                      status_message="boom")
        rows = list_sources(initialized_db)
        assert rows[0]["status"] == "failed"
        assert rows[0]["status_message"] == "boom"


class TestGetBytes:
    def test_get_source_bytes(self, initialized_db):
        b = _bytes("payload")
        row = insert_source(
            initialized_db, filename="t.pdf", sha256=_sha(b),
            size_bytes=len(b), blob=b, is_current=False,
        )
        out = get_source_bytes(initialized_db, row["id"])
        assert out == b


class TestDeleteCascade:
    def test_cascade_delete_chunks(self, initialized_db):
        pytest.importorskip("pymupdf")
        # Create the regulatory_chunks table out-of-band so the cascade
        # has something to find.
        from rag.regulatory.store import init_regulatory_table
        init_regulatory_table(initialized_db, embedding_dim=8)

        b = _bytes("c")
        row = insert_source(
            initialized_db, filename="t.pdf", sha256=_sha(b),
            size_bytes=len(b), blob=b, is_current=False,
        )
        # Insert a fake chunk row tagged with this source_id.
        cur = initialized_db.cursor()
        cur.execute(
            """
            INSERT INTO regulatory_chunks (embedding, content, breadcrumb, metadata)
            VALUES (%s::vector, %s, %s, %s::jsonb);
            """,
            ("[" + ",".join("0.0" for _ in range(8)) + "]", "body", "crumb",
             '{"source_id": "' + row["id"] + '", "citation": "x", "chunk_index": 0, "subsection": null}'),
        )
        deleted = cascade_delete_chunks(initialized_db, row["id"])
        assert deleted == 1

        delete_source(initialized_db, row["id"])
        assert list_sources(initialized_db) == []
