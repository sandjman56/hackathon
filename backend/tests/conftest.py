"""Shared pytest fixtures.

Each test function gets a fresh psycopg2 connection wrapped in a
transaction that ALWAYS rolls back at the end. The application code
calls ``commit()``, but because the test owns the outer transaction
via ``BEGIN``, those commits become savepoints relative to the test —
nothing actually persists. This keeps the test DB clean without
truncating tables between runs.

Requires DATABASE_URL to point at a *test* database.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
import pytest

# Make backend/ importable when pytest is run from the repo root.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))


def _require_test_db() -> str:
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL / DATABASE_URL not set; skipping DB tests")
    return url


@pytest.fixture
def db_conn():
    url = _require_test_db()
    conn = psycopg2.connect(url)
    conn.autocommit = False
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def stub_embedder():
    from tests.fixtures.stub_embedder import StubEmbeddingProvider
    return StubEmbeddingProvider(dim=8)
