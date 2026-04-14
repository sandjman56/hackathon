"""Verify init_db() schema changes are idempotent and add expected columns."""
from __future__ import annotations

import os
import psycopg2
import pytest

from db.vector_store import init_db


def _fetch_columns(conn, table: str) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type
              FROM information_schema.columns
             WHERE table_name = %s
            """,
            (table,),
        )
        return {row[0]: row[1] for row in cur.fetchall()}


@pytest.fixture
def fresh_conn():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    conn = psycopg2.connect(url)
    try:
        yield conn
    finally:
        conn.close()


def test_init_db_adds_ecfr_columns_to_regulatory_sources(fresh_conn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    init_db()
    cols = _fetch_columns(fresh_conn, "regulatory_sources")
    assert "source_type" in cols
    assert "content_type" in cols
    assert "effective_date" in cols
    assert cols["effective_date"] == "date"
    assert "cfr_title" in cols
    assert "cfr_part" in cols


def test_init_db_creates_ingest_log_table(fresh_conn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    init_db()
    cols = _fetch_columns(fresh_conn, "regulatory_ingest_log")
    assert cols, "regulatory_ingest_log not created"
    assert "correlation_id" in cols
    assert "trigger" in cols
    assert "status" in cols


def test_init_db_is_idempotent(fresh_conn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    init_db()
    init_db()  # second call must not raise
    cols = _fetch_columns(fresh_conn, "regulatory_sources")
    assert "source_type" in cols


def test_partial_unique_index_exists(fresh_conn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    init_db()
    with fresh_conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexdef FROM pg_indexes
             WHERE indexname = 'regulatory_sources_identity_idx'
            """
        )
        row = cur.fetchone()
    assert row is not None
    indexdef = row[0]
    assert "WHERE" in indexdef, f"partial index missing WHERE clause: {indexdef}"
    assert "source_type = 'ecfr'" in indexdef, \
        f"partial index predicate not scoped to source_type = 'ecfr': {indexdef}"
