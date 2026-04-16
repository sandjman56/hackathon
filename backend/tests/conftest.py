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


class _NoCommitConnection:
    """Thin wrapper around a psycopg2 connection that turns commit() into a
    no-op. psycopg2 C-extension connections don't allow monkey-patching
    ``commit``, so we delegate everything except commit.
    """
    def __init__(self, real_conn):
        self._conn = real_conn

    def commit(self):
        pass  # swallow — the fixture rollback undoes everything

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.fixture
def db_conn():
    """Yield a psycopg2 connection that rolls back everything on teardown.

    Repo functions call ``conn.commit()`` after each write. That would
    persist state across tests, so we wrap the connection to make
    ``commit`` a no-op. All work happens inside a single transaction,
    and the ``rollback()`` in ``finally`` undoes it on teardown.
    """
    url = _require_test_db()
    conn = psycopg2.connect(url)
    conn.autocommit = False
    wrapper = _NoCommitConnection(conn)
    try:
        yield wrapper
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


@pytest.fixture
def stub_embedder():
    from tests.fixtures.stub_embedder import StubEmbeddingProvider
    return StubEmbeddingProvider(dim=8)


@pytest.fixture(scope="session")
def sample_eis_bytes() -> bytes:
    from tests.fixtures.eis.build_sample import build_sample_eis_bytes
    return build_sample_eis_bytes()
