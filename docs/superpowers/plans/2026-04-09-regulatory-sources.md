# Regulatory Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PR #14's filesystem-glob source discovery with a Postgres-backed `regulatory_sources` table that supports drag-and-drop PDF upload, live embedding progress, deletion, and wires the `RegulatoryScreeningAgent` to actually query `regulatory_chunks`.

**Architecture:** A new repository module owns the `regulatory_sources` table (BYTEA + status + progress counters). Multipart upload returns 202 immediately and runs parse → chunk → embed in a FastAPI `BackgroundTasks` job that streams progress updates back to the row. The frontend modal polls every 2s while anything is in flight, renders a per-row progress bar with client-computed ETA, and supports drag-drop + delete with chunk cascade. The agent embeds a project-context query and runs cosine search via the existing `search_regulations()` helper.

**Tech Stack:** FastAPI · psycopg2 · pgvector · PyMuPDF · React 18 + Vite · Vitest + @testing-library/react · pytest

---

## File Structure

**Backend — new files:**
- `backend/db/regulatory_sources.py` — repository for the `regulatory_sources` table (init, insert, list, get_bytes, update_progress, update_status, delete, find_by_sha256, auto-import seed)
- `backend/services/regulatory_ingest.py` — background ingestion task (parse → chunk → embed → upsert), pure orchestration so it can be unit-tested
- `backend/tests/conftest.py` — shared pytest fixtures (test DB connection, transactional rollback, FastAPI TestClient, stub embedding provider)
- `backend/tests/test_regulatory_sources_repo.py` — repository unit tests
- `backend/tests/test_regulatory_sources_api.py` — FastAPI API tests
- `backend/tests/test_regulatory_ingest.py` — end-to-end ingestion test using the real seed PDF
- `backend/tests/test_regulatory_agent.py` — agent retrieval tests
- `backend/tests/fixtures/__init__.py`
- `backend/tests/fixtures/stub_embedder.py` — `StubEmbeddingProvider` returning fixed-dim zero vectors
- `backend/requirements-test.txt` — pytest, pytest-asyncio, httpx (for TestClient)

**Backend — modified files:**
- `backend/rag/regulatory/parser.py:297-319` — `parse_pdf` accepts `bytes | str` and uses `pymupdf.open(stream=...)` when given bytes
- `backend/rag/regulatory/embedder.py:40-71` — `embed_chunks` adds `on_progress: Callable[[int, int], None] | None` callback
- `backend/rag/regulatory/store.py:105-165` — `build_metadata` accepts a `source_id: str` arg and writes it into the metadata dict
- `backend/main.py:174-273` — replace old `/api/regulations/*` endpoints; add multipart upload, single-row GET, DELETE; lifespan auto-import
- `backend/agents/regulatory_screening.py` — full rewrite, takes `(llm, embedding_provider)`, runs real RAG
- `backend/pipeline.py:151-178, 301` — `_make_agent_node` and the inline `agent_class(llm)` call pass `embedding_provider` through

**Frontend — new files:**
- `frontend/src/components/SourcesModal.test.jsx` — modal rendering, upload, polling, delete
- `frontend/src/components/AgentPipeline.test.jsx` — VIEW SOURCES button regression test
- `frontend/vitest.config.js` — Vitest config that piggybacks on `vite.config.js`
- `frontend/src/test/setup.js` — `@testing-library/jest-dom` extensions

**Frontend — modified files:**
- `frontend/package.json` — add `test` script + Vitest, jsdom, @testing-library/react, @testing-library/jest-dom, @testing-library/user-event devDeps
- `frontend/src/components/SourcesModal.jsx` — full rewrite (drop zone, polling, progress bar, ETA, delete, status states)

**Docs:**
- `docs/superpowers/plans/2026-04-09-regulatory-sources.md` (this file)

---

## Task 1: Add backend test infrastructure

**Files:**
- Create: `backend/requirements-test.txt`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/fixtures/__init__.py`
- Create: `backend/tests/fixtures/stub_embedder.py`

- [ ] **Step 1: Create `backend/requirements-test.txt`**

```
pytest>=8.0
pytest-asyncio>=0.23
httpx>=0.27
```

- [ ] **Step 2: Install test deps**

Run: `cd backend && pip install -r requirements-test.txt`
Expected: installs cleanly.

- [ ] **Step 3: Create `backend/tests/fixtures/__init__.py`**

```python
```

(empty file — makes it a package)

- [ ] **Step 4: Create `backend/tests/fixtures/stub_embedder.py`**

```python
"""Offline embedding provider for tests.

Returns deterministic, fixed-dimension vectors so ingestion tests run
without hitting OpenAI/Gemini.
"""
from __future__ import annotations


class StubEmbeddingProvider:
    provider_name = "stub"

    def __init__(self, dim: int = 8):
        self.dim = dim
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        # Deterministic but not all-zero so cosine search has signal
        h = abs(hash(text)) % 1000
        return [(h + i) / 1000.0 for i in range(self.dim)]
```

- [ ] **Step 5: Create `backend/tests/conftest.py`**

```python
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
```

- [ ] **Step 6: Sanity-check pytest discovers the conftest**

Run: `cd backend && pytest tests/ --collect-only -q 2>&1 | head -20`
Expected: collects existing `test_regulatory_parser.py` and `test_project_parser.py` without import errors.

- [ ] **Step 7: Commit**

```bash
git add backend/requirements-test.txt backend/tests/conftest.py backend/tests/fixtures/
git commit -m "test: add pytest infrastructure (conftest, stub embedder)"
```

---

## Task 2: Make `parse_pdf` accept bytes

**Files:**
- Modify: `backend/rag/regulatory/parser.py:297-319`
- Test: `backend/tests/test_regulatory_parser.py`

- [ ] **Step 1: Add a failing test in `backend/tests/test_regulatory_parser.py`**

Append at the bottom of the file (before the `if __name__ == "__main__":` line if present, otherwise at end):

```python
class TestParsePdfFromBytes(unittest.TestCase):
    """parse_pdf must accept raw bytes so we can parse from DB BYTEA
    without writing the PDF to disk first."""

    def test_parse_pdf_accepts_bytes(self):
        pdf_path = BACKEND_DIR / "NEPA-40CFR1500_1508.pdf"
        if not pdf_path.exists():
            self.skipTest("real PDF not present")
        raw = pdf_path.read_bytes()
        sections, warnings = parse_pdf(raw)
        self.assertGreater(len(sections), 50,
                           "should parse the same sections from bytes as from path")
```

The test references `BACKEND_DIR`. If it's not already imported at the top of `test_regulatory_parser.py`, add this near the existing imports:

```python
BACKEND_DIR = Path(__file__).resolve().parent.parent
```

- [ ] **Step 2: Run the test, expect a failure**

Run: `cd backend && pytest tests/test_regulatory_parser.py::TestParsePdfFromBytes -v`
Expected: FAIL — `pymupdf.open()` rejects `bytes` as the path arg.

- [ ] **Step 3: Modify `parse_pdf` to accept bytes**

In `backend/rag/regulatory/parser.py`, replace the function signature and the `pymupdf.open` call:

```python
def parse_pdf(pdf_source: "str | bytes | Path") -> tuple[list[RawSection], list[str]]:
    """Parse a NEPA-style legal PDF into ordered RawSection records.

    Args:
        pdf_source: Either a filesystem path (``str`` / ``Path``) or the
            raw PDF bytes. Bytes are passed through to PyMuPDF as a
            stream so callers don't have to write to disk.

    Returns:
        ``(sections, warnings)`` — ``sections`` is the ordered list of
        :class:`RawSection`; ``warnings`` collects character-recovery
        diagnostics and any unclassified bold headers we encountered.
    """
    if isinstance(pdf_source, (bytes, bytearray)):
        doc = pymupdf.open(stream=bytes(pdf_source), filetype="pdf")
    else:
        doc = pymupdf.open(str(pdf_source))
    warnings: list[str] = []
    # ... rest of function unchanged ...
```

(Keep every line below `warnings: list[str] = []` exactly as it is.)

Add `from pathlib import Path` to the imports at the top of the file if it isn't already there.

- [ ] **Step 4: Run the test, expect pass**

Run: `cd backend && pytest tests/test_regulatory_parser.py::TestParsePdfFromBytes -v`
Expected: PASS.

- [ ] **Step 5: Run the full parser test file to make sure path-based parsing still works**

Run: `cd backend && pytest tests/test_regulatory_parser.py -v`
Expected: all tests pass (the existing 20 + the new one).

- [ ] **Step 6: Commit**

```bash
git add backend/rag/regulatory/parser.py backend/tests/test_regulatory_parser.py
git commit -m "feat(parser): accept raw PDF bytes via pymupdf stream"
```

---

## Task 3: Add `on_progress` callback to `embed_chunks`

**Files:**
- Modify: `backend/rag/regulatory/embedder.py:40-71`
- Test: `backend/tests/test_regulatory_embedder.py` (new)

- [ ] **Step 1: Create the failing test `backend/tests/test_regulatory_embedder.py`**

```python
"""Tests for embed_chunks progress callback."""
from __future__ import annotations

import asyncio
import unittest

from rag.regulatory.chunker import Chunk
from rag.regulatory.parser import DocumentType, RawSection
from tests.fixtures.stub_embedder import StubEmbeddingProvider


def _make_chunk(i: int) -> Chunk:
    section = RawSection(
        document_type=DocumentType.CFR_REGULATION,
        section=f"1500.{i}",
        title=f"Test section {i}",
        body=f"Body of section {i}.",
        citation=f"40 CFR §1500.{i}",
        pages=[1],
        part="1500",
        part_title="Purpose, Policy, and Mandate",
    )
    return Chunk(
        sources=[section],
        body=section.body,
        chunk_index=0,
        total_chunks_in_section=1,
        token_count=10,
    )


class TestEmbedChunksProgress(unittest.TestCase):
    def test_callback_fires_for_each_chunk(self):
        from rag.regulatory.embedder import embed_chunks
        chunks = [_make_chunk(i) for i in range(5)]
        provider = StubEmbeddingProvider(dim=8)
        progress_calls: list[tuple[int, int]] = []

        def on_progress(done: int, total: int) -> None:
            progress_calls.append((done, total))

        results = asyncio.run(
            embed_chunks(chunks, provider, concurrency=2, on_progress=on_progress)
        )

        self.assertEqual(len(results), 5)
        # Each chunk fires the callback exactly once
        self.assertEqual(len(progress_calls), 5)
        # Final call reports done == total
        self.assertEqual(progress_calls[-1][1], 5)
        self.assertEqual(progress_calls[-1][0], 5)
        # All counts are monotonically non-decreasing
        for prev, curr in zip(progress_calls, progress_calls[1:]):
            self.assertLessEqual(prev[0], curr[0])

    def test_no_callback_works(self):
        from rag.regulatory.embedder import embed_chunks
        chunks = [_make_chunk(0)]
        provider = StubEmbeddingProvider(dim=8)
        results = asyncio.run(embed_chunks(chunks, provider, concurrency=1))
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test, expect failure**

Run: `cd backend && pytest tests/test_regulatory_embedder.py -v`
Expected: FAIL — `embed_chunks` does not accept `on_progress`.

- [ ] **Step 3: Modify `embed_chunks` in `backend/rag/regulatory/embedder.py`**

Replace the function with:

```python
from typing import Any, Callable, Optional


async def embed_chunks(
    chunks: list[Chunk],
    provider: Any,
    concurrency: int = 4,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> list[tuple[str, list[float]]]:
    """Embed many chunks with bounded concurrency.

    Args:
        chunks: Chunks to embed (order preserved in the result).
        provider: An :class:`LLMProvider` instance with ``embed()``.
        concurrency: Max in-flight embedding calls.
        on_progress: Optional callback fired after each chunk completes,
            invoked with ``(done, total)``. Used by the ingestion task
            to update the live progress counter on a sources row.

    Returns:
        A list of ``(breadcrumb, vector)`` tuples in the same order as
        the input chunks.
    """
    sem = asyncio.Semaphore(concurrency)
    total = len(chunks)
    done = 0
    done_lock = asyncio.Lock()
    results: list[Optional[tuple[str, list[float]]]] = [None] * total

    async def _one(idx: int, c: Chunk) -> None:
        nonlocal done
        async with sem:
            try:
                results[idx] = await embed_chunk(c, provider)
            except Exception:
                logger.exception(
                    "Embedding failed for %s",
                    c.sources[0].citation if c.sources else "<unknown>",
                )
                raise
        if on_progress is not None:
            async with done_lock:
                done += 1
                try:
                    on_progress(done, total)
                except Exception:
                    logger.exception("on_progress callback raised; ignoring")

    await asyncio.gather(*(_one(i, c) for i, c in enumerate(chunks)))
    # mypy: results is now fully populated
    return [r for r in results if r is not None]
```

(Move the existing `from typing import Any` import to add `Callable, Optional`. Keep `embed_chunk`, `embedding_text`, and `detect_embedding_dimension` exactly as they are.)

- [ ] **Step 4: Run the test, expect pass**

Run: `cd backend && pytest tests/test_regulatory_embedder.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add backend/rag/regulatory/embedder.py backend/tests/test_regulatory_embedder.py
git commit -m "feat(embedder): on_progress callback for live embedding progress"
```

---

## Task 4: Thread `source_id` through chunk metadata

**Files:**
- Modify: `backend/rag/regulatory/store.py:105-165`
- Test: `backend/tests/test_regulatory_store.py` (new)

- [ ] **Step 1: Create the failing test `backend/tests/test_regulatory_store.py`**

```python
"""Unit tests for store.build_metadata source_id threading."""
from __future__ import annotations

import unittest

from rag.regulatory.chunker import Chunk
from rag.regulatory.parser import DocumentType, RawSection
from rag.regulatory.store import build_metadata


class TestBuildMetadataSourceId(unittest.TestCase):
    def test_source_id_in_metadata(self):
        section = RawSection(
            document_type=DocumentType.CFR_REGULATION,
            section="1500.1",
            title="Purpose",
            body="The purpose of this section is...",
            citation="40 CFR §1500.1",
            pages=[1],
            part="1500",
            part_title="Purpose, Policy, and Mandate",
        )
        chunk = Chunk(
            sources=[section],
            body=section.body,
            chunk_index=0,
            total_chunks_in_section=1,
            token_count=20,
        )
        meta = build_metadata(
            chunk,
            "40 CFR > Part 1500 > §1500.1",
            source="40_CFR_1500-1508",
            source_file="NEPA-40CFR1500_1508.pdf",
            source_id="abc-123",
            is_current=True,
        )
        self.assertEqual(meta["source_id"], "abc-123")
        self.assertEqual(meta["source_file"], "NEPA-40CFR1500_1508.pdf")
        self.assertTrue(meta["is_current"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test, expect failure**

Run: `cd backend && pytest tests/test_regulatory_store.py -v`
Expected: FAIL — `build_metadata` does not accept `source_id`.

- [ ] **Step 3: Add `source_id` to `build_metadata` in `backend/rag/regulatory/store.py`**

Change the signature and the returned dict. The new signature:

```python
def build_metadata(
    chunk: Chunk,
    breadcrumb: str,
    *,
    source: str,
    source_file: str,
    source_id: str,
    is_current: bool,
) -> dict:
```

In the returned dict, add `"source_id": source_id,` directly after `"source_file": source_file,`. Leave every other field exactly as it was.

Update the existing caller in `backend/main.py:255-262` (the old `/api/regulations/ingest` handler) to pass `source_id=""` for now — Task 7 replaces that whole endpoint anyway. This keeps the file importable in the meantime.

- [ ] **Step 4: Run the test, expect pass**

Run: `cd backend && pytest tests/test_regulatory_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/rag/regulatory/store.py backend/main.py backend/tests/test_regulatory_store.py
git commit -m "feat(store): thread source_id through chunk metadata"
```

---

## Task 5: Repository module `regulatory_sources`

**Files:**
- Create: `backend/db/regulatory_sources.py`
- Test: `backend/tests/test_regulatory_sources_repo.py`

- [ ] **Step 1: Create the failing test `backend/tests/test_regulatory_sources_repo.py`**

```python
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
```

- [ ] **Step 2: Run the test, expect import failure**

Run: `cd backend && pytest tests/test_regulatory_sources_repo.py -v`
Expected: FAIL — `db.regulatory_sources` does not exist.

- [ ] **Step 3: Create `backend/db/regulatory_sources.py`**

```python
"""Repository for the regulatory_sources table.

Holds the PDF bytes (BYTEA), upload metadata, and live ingestion progress.
The bytes column is intentionally excluded from list queries — only
``get_source_bytes()`` returns it. All access is raw psycopg2 to match
the rest of the project.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import psycopg2
import psycopg2.extras

from rag.regulatory.store import DEFAULT_TABLE as CHUNKS_TABLE

logger = logging.getLogger("eia.db.regulatory_sources")

TABLE = "regulatory_sources"


_LIST_COLUMNS = """
    id::text,
    filename,
    sha256,
    size_bytes,
    uploaded_at,
    status,
    status_message,
    chunks_total,
    chunks_embedded,
    chunk_count,
    sections_count,
    parser_warnings,
    embedding_dim,
    embedding_started_at,
    embedding_finished_at,
    is_current
"""


def init_regulatory_sources_table(conn: Any) -> None:
    """Create the table and its indexes if missing. Idempotent."""
    with conn.cursor() as cur:
        cur.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                filename              TEXT        NOT NULL,
                sha256                TEXT        NOT NULL UNIQUE,
                size_bytes            BIGINT      NOT NULL,
                bytes                 BYTEA       NOT NULL,
                uploaded_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                status                TEXT        NOT NULL DEFAULT 'pending',
                status_message        TEXT,
                chunks_total          INT,
                chunks_embedded       INT         NOT NULL DEFAULT 0,
                chunk_count           INT         NOT NULL DEFAULT 0,
                sections_count        INT         NOT NULL DEFAULT 0,
                parser_warnings       INT         NOT NULL DEFAULT 0,
                embedding_dim         INT,
                embedding_started_at  TIMESTAMPTZ,
                embedding_finished_at TIMESTAMPTZ,
                is_current            BOOLEAN     NOT NULL DEFAULT FALSE
            );
            """
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {TABLE}_status_idx ON {TABLE} (status);"
        )
    conn.commit()
    logger.info("Initialized %s", TABLE)


def insert_source(
    conn: Any,
    *,
    filename: str,
    sha256: str,
    size_bytes: int,
    blob: bytes,
    is_current: bool,
) -> dict:
    """Insert a row, or return the existing one if sha256 already exists."""
    existing = find_by_sha256(conn, sha256)
    if existing is not None:
        logger.info("insert_source: dedup hit for sha256=%s", sha256[:12])
        return existing

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            INSERT INTO {TABLE}
                (filename, sha256, size_bytes, bytes, is_current)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING {_LIST_COLUMNS};
            """,
            (filename, sha256, size_bytes, psycopg2.Binary(blob), is_current),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("insert_source: INSERT ... RETURNING returned no row")
    conn.commit()
    return _normalize(row)


def find_by_sha256(conn: Any, sha256: str) -> Optional[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_LIST_COLUMNS} FROM {TABLE} WHERE sha256 = %s;",
            (sha256,),
        )
        row = cur.fetchone()
    return _normalize(row) if row else None


def get_source_by_id(conn: Any, source_id: str) -> Optional[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_LIST_COLUMNS} FROM {TABLE} WHERE id = %s;",
            (source_id,),
        )
        row = cur.fetchone()
    return _normalize(row) if row else None


def list_sources(conn: Any) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_LIST_COLUMNS} FROM {TABLE} ORDER BY uploaded_at DESC;"
        )
        rows = cur.fetchall()
    return [_normalize(r) for r in rows]


def get_source_bytes(conn: Any, source_id: str) -> Optional[bytes]:
    """Stream the BYTEA column for one row. Used by the ingest task."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT bytes FROM {TABLE} WHERE id = %s;", (source_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return bytes(row[0])


def update_status(
    conn: Any,
    source_id: str,
    *,
    status: str,
    status_message: Optional[str] = None,
    chunks_total: Optional[int] = None,
    sections_count: Optional[int] = None,
    parser_warnings: Optional[int] = None,
    embedding_dim: Optional[int] = None,
    chunk_count: Optional[int] = None,
    started_at_now: bool = False,
    finished_at_now: bool = False,
) -> None:
    sets: list[str] = ["status = %s"]
    args: list[Any] = [status]
    if status_message is not None:
        sets.append("status_message = %s"); args.append(status_message)
    if chunks_total is not None:
        sets.append("chunks_total = %s"); args.append(chunks_total)
    if sections_count is not None:
        sets.append("sections_count = %s"); args.append(sections_count)
    if parser_warnings is not None:
        sets.append("parser_warnings = %s"); args.append(parser_warnings)
    if embedding_dim is not None:
        sets.append("embedding_dim = %s"); args.append(embedding_dim)
    if chunk_count is not None:
        sets.append("chunk_count = %s"); args.append(chunk_count)
    if started_at_now:
        sets.append("embedding_started_at = NOW()")
    if finished_at_now:
        sets.append("embedding_finished_at = NOW()")
    args.append(source_id)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {TABLE} SET {', '.join(sets)} WHERE id = %s;",
            tuple(args),
        )
    conn.commit()


def update_progress(conn: Any, source_id: str, chunks_embedded: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {TABLE} SET chunks_embedded = %s WHERE id = %s;",
            (chunks_embedded, source_id),
        )
    conn.commit()


def cascade_delete_chunks(conn: Any, source_id: str) -> int:
    """Delete all chunks belonging to a source. Returns the row count."""
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {CHUNKS_TABLE} WHERE metadata->>'source_id' = %s;",
            (source_id,),
        )
        n = cur.rowcount
    conn.commit()
    return n


def delete_source(conn: Any, source_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {TABLE} WHERE id = %s;", (source_id,))
    conn.commit()


def is_empty(conn: Any) -> bool:
    with conn.cursor() as cur:
        cur.execute(f"SELECT 1 FROM {TABLE} LIMIT 1;")
        return cur.fetchone() is None


def _normalize(row: Optional[dict]) -> Optional[dict]:
    """Convert datetime / UUID values to ISO strings for JSON safety."""
    if row is None:
        return None
    out = dict(row)
    for k in ("uploaded_at", "embedding_started_at", "embedding_finished_at"):
        v = out.get(k)
        if v is not None and hasattr(v, "isoformat"):
            out[k] = v.isoformat()
    return out
```

- [ ] **Step 4: Run the repo tests**

Run: `cd backend && TEST_DATABASE_URL=$DATABASE_URL pytest tests/test_regulatory_sources_repo.py -v`
Expected: all tests pass. (If the developer doesn't have a test DB, the conftest will skip.)

- [ ] **Step 5: Commit**

```bash
git add backend/db/regulatory_sources.py backend/tests/test_regulatory_sources_repo.py
git commit -m "feat(db): regulatory_sources repository module"
```

---

## Task 6: Background ingestion service

**Files:**
- Create: `backend/services/__init__.py`
- Create: `backend/services/regulatory_ingest.py`
- Test: `backend/tests/test_regulatory_ingest.py`

- [ ] **Step 1: Create `backend/services/__init__.py`**

```python
```

(empty file)

- [ ] **Step 2: Create the failing test `backend/tests/test_regulatory_ingest.py`**

```python
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
```

- [ ] **Step 3: Run the test, expect failure**

Run: `cd backend && TEST_DATABASE_URL=$DATABASE_URL pytest tests/test_regulatory_ingest.py -v`
Expected: FAIL — `services.regulatory_ingest` does not exist.

- [ ] **Step 4: Create `backend/services/regulatory_ingest.py`**

```python
"""Background ingestion: parse → chunk → embed → upsert.

Designed to be invoked from FastAPI BackgroundTasks. Synchronous wrapper
for tests, async-friendly internals so embedding can fan out via the
existing embedder helper.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from db.regulatory_sources import (
    cascade_delete_chunks,
    get_source_bytes,
    update_progress,
    update_status,
)
from rag.regulatory.chunker import chunk_sections
from rag.regulatory.embedder import detect_embedding_dimension, embed_chunks
from rag.regulatory.parser import parse_pdf
from rag.regulatory.store import (
    build_metadata,
    init_regulatory_table,
    upsert_chunks,
)

logger = logging.getLogger("eia.rag.regulatory.sources")

# Throttle progress writes so we don't hammer the DB on small chunks.
_PROGRESS_MIN_INTERVAL_S = 1.0
_PROGRESS_MIN_DELTA = 5


def ingest_source_sync(
    conn: Any,
    *,
    source_id: str,
    embedding_provider: Any,
    correlation_id: str | None = None,
) -> None:
    """Run ingestion synchronously against an open psycopg2 connection.

    The connection MUST be writable. The HTTP layer should pass a fresh
    connection (NOT the request connection) so background work doesn't
    interfere with request lifecycle.
    """
    cid = correlation_id or uuid.uuid4().hex[:8]
    log = lambda msg, *args: logger.info(f"[sources:{cid}] " + msg, *args)
    warn = lambda msg, *args: logger.warning(f"[sources:{cid}] " + msg, *args)
    err = lambda msg, *args: logger.error(f"[sources:{cid}] " + msg, *args)

    try:
        log("ingest start: source_id=%s", source_id)
        update_status(conn, source_id, status="embedding",
                      started_at_now=True)

        blob = get_source_bytes(conn, source_id)
        if blob is None:
            raise RuntimeError(f"source row not found: {source_id}")

        log("parse_pdf begin: %d bytes", len(blob))
        t0 = time.time()
        sections, parser_warnings = parse_pdf(blob)
        log("parse_pdf done: %d sections, %d warnings in %.2fs",
            len(sections), len(parser_warnings), time.time() - t0)

        if not sections:
            warn("zero sections detected — marking failed")
            update_status(
                conn, source_id, status="failed",
                status_message=(
                    "Not a NEPA-style PDF (no CFR sections detected). "
                    "Only documents structured like 40 CFR 1500-1508 "
                    "can be ingested."
                ),
            )
            return

        log("chunking begin")
        t0 = time.time()
        chunks = chunk_sections(sections)
        log("chunking done: %d chunks in %.2fs", len(chunks), time.time() - t0)

        dim = detect_embedding_dimension(embedding_provider)
        log("embedding dim=%d  chunks_total=%d", dim, len(chunks))
        update_status(
            conn, source_id, status="embedding",
            chunks_total=len(chunks),
            sections_count=len(sections),
            parser_warnings=len(parser_warnings),
            embedding_dim=dim,
        )

        # Throttled progress callback
        last_write_t = [0.0]
        last_write_n = [0]

        def on_progress(done: int, total: int) -> None:
            now = time.time()
            if (
                done == total
                or now - last_write_t[0] >= _PROGRESS_MIN_INTERVAL_S
                or done - last_write_n[0] >= _PROGRESS_MIN_DELTA
            ):
                update_progress(conn, source_id, chunks_embedded=done)
                last_write_t[0] = now
                last_write_n[0] = done
                log("embedding progress: %d/%d", done, total)

        log("embedding begin")
        t0 = time.time()
        embeddings = asyncio.run(
            embed_chunks(chunks, embedding_provider, concurrency=4,
                         on_progress=on_progress)
        )
        log("embedding done in %.2fs", time.time() - t0)

        # Build rows + upsert
        init_regulatory_table(conn, embedding_dim=dim)
        from db.regulatory_sources import get_source_by_id
        row = get_source_by_id(conn, source_id)
        if row is None:
            raise RuntimeError(f"row vanished mid-ingest: {source_id}")
        rows = []
        for chunk, (breadcrumb, vec) in zip(chunks, embeddings):
            meta = build_metadata(
                chunk,
                breadcrumb,
                source=row["filename"].rsplit(".", 1)[0],
                source_file=row["filename"],
                source_id=source_id,
                is_current=row["is_current"],
            )
            rows.append((chunk, breadcrumb, vec, meta))

        # Idempotent re-embed: clear old chunks for this source first
        cascade_delete_chunks(conn, source_id)
        written = upsert_chunks(conn, rows)
        log("upserted %d chunks", written)

        update_status(
            conn, source_id, status="ready",
            chunk_count=written, finished_at_now=True,
        )
        log("status → ready")

    except Exception as exc:
        err("ingest failed: %s", exc, exc_info=True)
        try:
            update_status(
                conn, source_id, status="failed",
                status_message=f"{type(exc).__name__}: {exc}",
            )
        except Exception:
            err("could not even write failure status", exc_info=True)
        # Do not re-raise — background task swallows exceptions silently
        # and we've recorded the state in the row.
```

- [ ] **Step 5: Run the ingest tests**

Run: `cd backend && TEST_DATABASE_URL=$DATABASE_URL pytest tests/test_regulatory_ingest.py -v`
Expected: both tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/services/__init__.py backend/services/regulatory_ingest.py backend/tests/test_regulatory_ingest.py
git commit -m "feat(services): background regulatory ingestion task"
```

---

## Task 7: Replace `/api/regulations/*` endpoints

**Files:**
- Modify: `backend/main.py:174-273` (the entire regulatory section)
- Test: `backend/tests/test_regulatory_sources_api.py`

- [ ] **Step 1: Create the failing test `backend/tests/test_regulatory_sources_api.py`**

```python
"""FastAPI endpoint tests for /api/regulations/sources.

Uses TestClient. The startup lifespan creates real providers, so we
override the embedding_provider on app.state with a stub before each
test.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
SEED_PDF = BACKEND_DIR / "NEPA-40CFR1500_1508.pdf"


@pytest.fixture
def client(stub_embedder, monkeypatch):
    # Stub the embedding provider so lifespan doesn't need a real API key
    from llm import provider_factory
    monkeypatch.setattr(provider_factory, "get_embedding_provider",
                        lambda: stub_embedder)

    class _StubLLM:
        provider_name = "stub-llm"
        def complete(self, *a, **k): return "[]"
        def embed(self, text): return stub_embedder.embed(text)

    monkeypatch.setattr(provider_factory, "get_llm_provider",
                        lambda: _StubLLM())

    from main import app
    with TestClient(app) as c:
        yield c


def test_list_sources_empty_or_seed(client):
    r = client.get("/api/regulations/sources")
    assert r.status_code == 200
    assert "sources" in r.json()
    # bytes never appears in the listing
    for s in r.json()["sources"]:
        assert "bytes" not in s


def test_upload_pdf_returns_202(client):
    if not SEED_PDF.exists():
        pytest.skip("seed PDF not present")
    raw = SEED_PDF.read_bytes()
    r = client.post(
        "/api/regulations/sources",
        files={"file": ("seed.pdf", raw, "application/pdf")},
        data={"is_current": "false"},
    )
    assert r.status_code in (200, 202)
    body = r.json()
    assert body["filename"] == "seed.pdf" or body["sha256"] == hashlib.sha256(raw).hexdigest()


def test_upload_dedupes_by_sha(client):
    if not SEED_PDF.exists():
        pytest.skip("seed PDF not present")
    raw = SEED_PDF.read_bytes()
    r1 = client.post(
        "/api/regulations/sources",
        files={"file": ("a.pdf", raw, "application/pdf")},
    )
    r2 = client.post(
        "/api/regulations/sources",
        files={"file": ("b.pdf", raw, "application/pdf")},
    )
    assert r1.json()["id"] == r2.json()["id"]


def test_upload_rejects_non_pdf(client):
    r = client.post(
        "/api/regulations/sources",
        files={"file": ("x.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400


def test_get_single_source(client):
    if not SEED_PDF.exists():
        pytest.skip("seed PDF not present")
    raw = SEED_PDF.read_bytes()
    r = client.post(
        "/api/regulations/sources",
        files={"file": ("seed.pdf", raw, "application/pdf")},
    )
    src_id = r.json()["id"]
    r2 = client.get(f"/api/regulations/sources/{src_id}")
    assert r2.status_code == 200
    body = r2.json()
    assert "chunks_embedded" in body
    assert "chunks_total" in body
    assert "bytes" not in body


def test_delete_source(client):
    if not SEED_PDF.exists():
        pytest.skip("seed PDF not present")
    raw = SEED_PDF.read_bytes()
    src_id = client.post(
        "/api/regulations/sources",
        files={"file": ("seed.pdf", raw, "application/pdf")},
    ).json()["id"]
    r = client.delete(f"/api/regulations/sources/{src_id}")
    assert r.status_code == 200
    assert "deleted_chunks" in r.json()
    # And it's gone from the list
    listed = client.get("/api/regulations/sources").json()["sources"]
    assert all(s["id"] != src_id for s in listed)
```

- [ ] **Step 2: Run the test, expect failure**

Run: `cd backend && TEST_DATABASE_URL=$DATABASE_URL pytest tests/test_regulatory_sources_api.py -v`
Expected: FAIL — endpoints don't exist yet (or have the wrong shape).

- [ ] **Step 3: Replace lines 174-273 in `backend/main.py`**

Delete the existing block from `# --- Regulatory sources (PDF discovery + ingestion) ----------------------` through the end of the `ingest_regulatory_pdf` function.

Add these imports at the top of the file with the others:

```python
import hashlib
import uuid
from typing import Optional

from fastapi import BackgroundTasks, File, Form, UploadFile

from db.regulatory_sources import (
    init_regulatory_sources_table,
    insert_source,
    list_sources,
    get_source_by_id,
    cascade_delete_chunks,
    delete_source,
    is_empty as sources_is_empty,
)
from services.regulatory_ingest import ingest_source_sync
```

In the `lifespan()` function, after `init_db()`, add:

```python
        # Initialize the regulatory sources table on every startup.
        try:
            _conn = _get_connection()
            init_regulatory_sources_table(_conn)
            _conn.close()
        except Exception as exc:
            print(f"[LIFESPAN] regulatory_sources init failed: {exc}",
                  flush=True, file=sys.stdout)
            raise
```

After the providers are wired onto `app.state`, add the auto-import:

```python
        # One-time seed: if there are no sources yet but the bundled
        # NEPA PDF is on disk, ingest it so the modal isn't empty on
        # first launch. Idempotent thanks to the sha256 unique constraint.
        try:
            _conn = _get_connection()
            if sources_is_empty(_conn):
                seed = _BACKEND_DIR / "NEPA-40CFR1500_1508.pdf"
                if seed.exists():
                    raw = seed.read_bytes()
                    sha = hashlib.sha256(raw).hexdigest()
                    row = insert_source(
                        _conn, filename=seed.name, sha256=sha,
                        size_bytes=len(raw), blob=raw, is_current=True,
                    )
                    print(f"[LIFESPAN] seeded {seed.name} as id={row['id']}",
                          flush=True, file=sys.stdout)
                    # Run ingest in-process; takes 30-90s on Gemini, OK for cold start
                    ingest_source_sync(
                        _conn, source_id=row["id"],
                        embedding_provider=app.state.embedding_provider,
                        correlation_id=f"seed{row['id'][:6]}",
                    )
            _conn.close()
        except Exception as exc:
            print(f"[LIFESPAN] auto-import failed (non-fatal): {exc}",
                  flush=True, file=sys.stdout)
```

(The auto-import is wrapped so it never blocks startup if it fails.)

Now add the new endpoints. Replace the deleted block with:

```python
# --- Regulatory sources (DB-backed uploads + ingestion) -------------------

_BACKEND_DIR = Path(__file__).resolve().parent
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB

_sources_logger = logging.getLogger("eia.rag.regulatory.sources")
if not any(isinstance(h, logging.StreamHandler) for h in _sources_logger.handlers):
    _sources_logger.addHandler(_stdout_handler)
_sources_logger.setLevel(logging.DEBUG)
_sources_logger.propagate = False


def _new_correlation_id() -> str:
    return uuid.uuid4().hex[:8]


@app.get("/api/regulations/sources")
def list_regulatory_sources():
    conn = _get_connection()
    try:
        return {"sources": list_sources(conn)}
    finally:
        conn.close()


@app.get("/api/regulations/sources/{source_id}")
def get_regulatory_source(source_id: str):
    conn = _get_connection()
    try:
        row = get_source_by_id(conn, source_id)
        if row is None:
            raise HTTPException(status_code=404, detail="source not found")
        return row
    finally:
        conn.close()


def _run_ingest_background(source_id: str, correlation_id: str):
    """Background task entrypoint. Opens its own DB connection."""
    conn = _get_connection()
    try:
        ingest_source_sync(
            conn,
            source_id=source_id,
            embedding_provider=app.state.embedding_provider,
            correlation_id=correlation_id,
        )
    finally:
        conn.close()


@app.post("/api/regulations/sources", status_code=202)
async def upload_regulatory_source(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    is_current: bool = Form(False),
):
    cid = _new_correlation_id()
    _sources_logger.info(
        "[sources:%s] upload received: filename=%s content_type=%s",
        cid, file.filename, file.content_type,
    )

    if file.content_type not in ("application/pdf", "application/x-pdf", "binary/octet-stream"):
        _sources_logger.warning("[sources:%s] rejected: bad content_type=%s",
                                cid, file.content_type)
        raise HTTPException(status_code=400, detail="file must be application/pdf")

    blob = await file.read()
    if len(blob) == 0:
        raise HTTPException(status_code=400, detail="empty file")
    if len(blob) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400,
                            detail=f"file too large (>{_MAX_UPLOAD_BYTES} bytes)")
    if not blob.startswith(b"%PDF"):
        _sources_logger.warning("[sources:%s] rejected: missing %%PDF magic", cid)
        raise HTTPException(status_code=400, detail="not a valid PDF (missing magic bytes)")

    sha = hashlib.sha256(blob).hexdigest()
    _sources_logger.info("[sources:%s] sha256=%s size=%d", cid, sha[:12], len(blob))

    conn = _get_connection()
    try:
        row = insert_source(
            conn,
            filename=file.filename or "upload.pdf",
            sha256=sha,
            size_bytes=len(blob),
            blob=blob,
            is_current=is_current,
        )
    finally:
        conn.close()

    # If the row already had ready chunks, skip re-ingestion.
    if row["status"] != "ready":
        _sources_logger.info("[sources:%s] queueing background ingest for id=%s",
                             cid, row["id"])
        background_tasks.add_task(_run_ingest_background, row["id"], cid)
    else:
        _sources_logger.info("[sources:%s] dedup hit, already ready, no ingest", cid)

    return row


@app.delete("/api/regulations/sources/{source_id}")
def delete_regulatory_source(source_id: str):
    conn = _get_connection()
    try:
        if get_source_by_id(conn, source_id) is None:
            raise HTTPException(status_code=404, detail="source not found")
        deleted_chunks = cascade_delete_chunks(conn, source_id)
        delete_source(conn, source_id)
        return {"deleted_chunks": deleted_chunks}
    finally:
        conn.close()
```

- [ ] **Step 4: Run the API tests**

Run: `cd backend && TEST_DATABASE_URL=$DATABASE_URL pytest tests/test_regulatory_sources_api.py -v`
Expected: all tests pass. The tests use a real BackgroundTasks runner which executes synchronously after the response in TestClient.

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && TEST_DATABASE_URL=$DATABASE_URL pytest tests/ -v`
Expected: all tests pass (existing parser tests + everything new).

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/tests/test_regulatory_sources_api.py
git commit -m "feat(api): DB-backed regulatory sources upload + delete endpoints"
```

---

## Task 8: Wire `RegulatoryScreeningAgent` for real RAG

**Files:**
- Modify: `backend/agents/regulatory_screening.py`
- Modify: `backend/pipeline.py:151-178, 301`
- Test: `backend/tests/test_regulatory_agent.py`

- [ ] **Step 1: Create the failing test `backend/tests/test_regulatory_agent.py`**

```python
"""Tests for the non-stub RegulatoryScreeningAgent."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from db.regulatory_sources import init_regulatory_sources_table
from rag.regulatory.store import init_regulatory_table


@pytest.fixture
def initialized(db_conn, stub_embedder):
    init_regulatory_sources_table(db_conn)
    init_regulatory_table(db_conn, embedding_dim=stub_embedder.dim)
    return db_conn, stub_embedder


def _seed_chunk(conn, source_id="src-1"):
    cur = conn.cursor()
    vec = "[" + ",".join("0.1" for _ in range(8)) + "]"
    cur.execute(
        """
        INSERT INTO regulatory_chunks (embedding, content, breadcrumb, metadata)
        VALUES (%s::vector, %s, %s, %s::jsonb);
        """,
        (vec, "When to prepare an EA per 40 CFR 1501.3.",
         "40 CFR > Part 1501 > §1501.3",
         json.dumps({
             "source_id": source_id,
             "citation": "40 CFR §1501.3",
             "chunk_index": 0,
             "subsection": None,
             "is_current": True,
         })),
    )
    conn.commit()


def test_agent_returns_regs_when_corpus_present(initialized, monkeypatch):
    conn, embedder = initialized
    _seed_chunk(conn)

    fake_llm = MagicMock()
    fake_llm.provider_name = "fake"
    fake_llm.complete.return_value = json.dumps([{
        "name": "NEPA Environmental Assessment",
        "jurisdiction": "Federal",
        "description": "Triggered by 40 CFR 1501.3.",
        "citation": "40 CFR §1501.3",
    }])

    # Patch _get_connection so the agent uses our test conn
    from agents import regulatory_screening as agent_mod
    monkeypatch.setattr(agent_mod, "_get_connection", lambda: conn)

    from agents.regulatory_screening import RegulatoryScreeningAgent
    agent = RegulatoryScreeningAgent(fake_llm, embedder)
    state = {
        "parsed_project": {"type": "highway widening", "scale": "5 mi"},
        "coordinates": "40.0,-79.0",
        "environmental_data": {
            "fema_flood_zones": {"in_sfha": True},
            "usfws_species": {"count": 2},
            "nwi_wetlands": {"count": 3},
            "usda_farmland": {"is_prime": False},
        },
    }
    out = agent.run(state)
    assert isinstance(out["regulations"], list)
    assert len(out["regulations"]) == 1
    assert out["regulations"][0]["citation"] == "40 CFR §1501.3"


def test_agent_empty_corpus_returns_empty(initialized, monkeypatch):
    conn, embedder = initialized
    fake_llm = MagicMock()
    fake_llm.provider_name = "fake"

    from agents import regulatory_screening as agent_mod
    monkeypatch.setattr(agent_mod, "_get_connection", lambda: conn)

    from agents.regulatory_screening import RegulatoryScreeningAgent
    agent = RegulatoryScreeningAgent(fake_llm, embedder)
    out = agent.run({
        "parsed_project": {},
        "coordinates": "0,0",
        "environmental_data": {},
    })
    assert out["regulations"] == []
    fake_llm.complete.assert_not_called()


def test_agent_invalid_llm_json_returns_empty(initialized, monkeypatch):
    conn, embedder = initialized
    _seed_chunk(conn)

    fake_llm = MagicMock()
    fake_llm.provider_name = "fake"
    fake_llm.complete.return_value = "not valid json at all"

    from agents import regulatory_screening as agent_mod
    monkeypatch.setattr(agent_mod, "_get_connection", lambda: conn)

    from agents.regulatory_screening import RegulatoryScreeningAgent
    agent = RegulatoryScreeningAgent(fake_llm, embedder)
    out = agent.run({
        "parsed_project": {"type": "x"},
        "coordinates": "0,0",
        "environmental_data": {},
    })
    assert out["regulations"] == []
```

- [ ] **Step 2: Run the test, expect failure**

Run: `cd backend && TEST_DATABASE_URL=$DATABASE_URL pytest tests/test_regulatory_agent.py -v`
Expected: FAIL — agent doesn't take 2 args, doesn't query DB.

- [ ] **Step 3: Rewrite `backend/agents/regulatory_screening.py`**

```python
import json
import logging
import re
import time
import uuid
from typing import Any

from db.vector_store import _get_connection
from llm.base import LLMProvider
from rag.regulatory.store import search_regulations

logger = logging.getLogger("eia.agents.regulatory_screening")

_TOP_K = 8


class RegulatoryScreeningAgent:
    """Real RAG: embed project context, cosine-search regulatory_chunks,
    ask the LLM to pick applicable regulations from the retrieved snippets."""

    def __init__(self, llm: LLMProvider, embedding_provider: Any):
        self.llm = llm
        self.embedding_provider = embedding_provider

    def run(self, state: dict) -> dict:
        cid = uuid.uuid4().hex[:8]
        log = lambda m, *a: logger.info(f"[regulatory:{cid}] " + m, *a)
        warn = lambda m, *a: logger.warning(f"[regulatory:{cid}] " + m, *a)
        err = lambda m, *a: logger.error(f"[regulatory:{cid}] " + m, *a)

        log("starting")
        try:
            query_text = self._build_query_text(state)
            log("query_text built: %d chars", len(query_text))

            t0 = time.time()
            query_vec = self.embedding_provider.embed(query_text)
            log("embedded query in %.2fs dim=%d",
                time.time() - t0, len(query_vec))

            conn = _get_connection()
            try:
                hits = search_regulations(
                    conn, query_vec, top_k=_TOP_K,
                    filters={"is_current": True},
                )
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
            log("retrieved %d chunks", len(hits))

            if not hits:
                warn("empty corpus or zero hits — returning []")
                state["regulations"] = []
                return state

            sims = [h.get("similarity", 0.0) for h in hits]
            log("similarity range %.2f-%.2f", min(sims), max(sims))

            prompt = self._build_prompt(state, hits)
            log("LLM call begin")
            t0 = time.time()
            raw = self.llm.complete(prompt)
            log("LLM returned in %.2fs (%d chars)", time.time() - t0, len(raw or ""))

            regs = self._parse_llm_json(raw)
            log("parsed %d regulations", len(regs))
            state["regulations"] = regs
            return state

        except Exception as exc:
            err("agent failed: %s", exc, exc_info=True)
            state["regulations"] = []
            return state

    # --- helpers --------------------------------------------------------

    def _build_query_text(self, state: dict) -> str:
        parsed = state.get("parsed_project") or {}
        env = state.get("environmental_data") or {}
        fema = env.get("fema_flood_zones") or {}
        species = env.get("usfws_species") or {}
        wetlands = env.get("nwi_wetlands") or {}
        farmland = env.get("usda_farmland") or {}

        parts = [
            f"Project type: {parsed.get('type', 'unknown')}",
            f"Scale: {parsed.get('scale', 'unknown')}",
            f"Coordinates: {state.get('coordinates', 'unknown')}",
            f"In SFHA: {fema.get('in_sfha', False)}",
            f"T&E species count: {species.get('count', 0)}",
            f"Wetland features: {wetlands.get('count', 0)}",
            f"Prime farmland: {farmland.get('is_prime', False)}",
        ]
        return " | ".join(parts)

    def _build_prompt(self, state: dict, hits: list[dict]) -> str:
        parsed = state.get("parsed_project") or {}
        env = state.get("environmental_data") or {}
        excerpt_lines = []
        for i, h in enumerate(hits, 1):
            meta = h.get("metadata") or {}
            excerpt_lines.append(
                f"[{i}] {h.get('breadcrumb', '')}  "
                f"(cite: {meta.get('citation', '?')}, "
                f"sim: {h.get('similarity', 0):.2f})\n"
                f"    {h.get('content', '').strip()}"
            )
        excerpts = "\n\n".join(excerpt_lines)
        return f"""You are a NEPA compliance assistant. Based on the project below
and the excerpts from the Code of Federal Regulations, return a JSON
array of regulations that apply. Each item:
  {{ "name": str, "jurisdiction": str, "description": str, "citation": str }}

Project:
  type: {parsed.get('type', 'unknown')}
  scale: {parsed.get('scale', 'unknown')}
  coordinates: {state.get('coordinates', 'unknown')}
  flags: in_sfha={env.get('fema_flood_zones', {}).get('in_sfha', False)}, \
species_count={env.get('usfws_species', {}).get('count', 0)}, \
wetlands={env.get('nwi_wetlands', {}).get('count', 0)}, \
prime_farmland={env.get('usda_farmland', {}).get('is_prime', False)}

Excerpts (top {len(hits)} by similarity):
{excerpts}

Return only valid JSON. Do not invent citations.
"""

    def _parse_llm_json(self, raw: str) -> list[dict]:
        if not raw:
            return []
        # Try to find a JSON array in the output (LLMs sometimes wrap in prose).
        m = re.search(r"\[[\s\S]*\]", raw)
        candidate = m.group(0) if m else raw
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            logger.debug("LLM returned unparseable JSON: %r", raw[:500])
            return []
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            out.append({
                "name": str(item.get("name", "")),
                "jurisdiction": str(item.get("jurisdiction", "")),
                "description": str(item.get("description", "")),
                "citation": str(item.get("citation", "")),
            })
        return out
```

- [ ] **Step 4: Update `backend/pipeline.py` to pass embedding_provider to the agent**

In `pipeline.py`, find the `_make_agent_node` function (around line 151). Change its signature and the agent instantiation:

```python
def _make_agent_node(agent_key: str, agent_class, llm: LLMProvider, embedding_provider: Any):
    """Create a LangGraph node function wrapping an agent's .run() call."""
    if agent_key == "regulatory_screening":
        agent = agent_class(llm, embedding_provider)
    else:
        agent = agent_class(llm)
    # ... rest unchanged
```

Find `build_pipeline(llm)` (around line 181) and change its signature:

```python
def build_pipeline(llm: LLMProvider, embedding_provider: Any):
    """Construct and compile the EIA LangGraph pipeline."""
    graph = StateGraph(EIAPipelineState)
    for agent_key, agent_class in AGENT_REGISTRY:
        graph.add_node(agent_key, _make_agent_node(agent_key, agent_class, llm, embedding_provider))
    # ... rest unchanged
```

In `run_eia_pipeline` (around line 194), update the signature and the `build_pipeline` call:

```python
def run_eia_pipeline(
    project_name: str,
    coordinates: str,
    description: str,
    llm: LLMProvider,
    embedding_provider: Any,
) -> dict:
    compiled = build_pipeline(llm, embedding_provider)
    # ... rest unchanged
```

In `stream_eia_pipeline` (around line 226), add `embedding_provider` to the signature:

```python
def stream_eia_pipeline(
    project_name: str,
    coordinates: str,
    description: str,
    llm: LLMProvider,
    embedding_provider: Any,
):
```

Inside `stream_eia_pipeline`, find the line `agent = agent_class(llm)` (around line 301) and replace with:

```python
            if agent_key == "regulatory_screening":
                agent = agent_class(llm, embedding_provider)
            else:
                agent = agent_class(llm)
```

Add `from typing import Any` to the top of the file if not present (it already imports `TypedDict`, so add `Any` to that line: `from typing import Any, TypedDict`).

- [ ] **Step 5: Update `backend/main.py` to pass embedding_provider to the streaming pipeline**

In `backend/main.py`, find the `run_pipeline` endpoint (around line 94):

```python
@app.post("/api/run")
def run_pipeline(req: RunRequest):
    return StreamingResponse(
        stream_eia_pipeline(
            project_name=req.project_name,
            coordinates=req.coordinates,
            description=req.description,
            llm=app.state.llm_provider,
            embedding_provider=app.state.embedding_provider,
        ),
        ...
```

Add `embedding_provider=app.state.embedding_provider,` to the kwargs.

- [ ] **Step 6: Run the agent tests**

Run: `cd backend && TEST_DATABASE_URL=$DATABASE_URL pytest tests/test_regulatory_agent.py -v`
Expected: all 3 tests pass.

- [ ] **Step 7: Run the full backend test suite**

Run: `cd backend && TEST_DATABASE_URL=$DATABASE_URL pytest tests/ -v`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/agents/regulatory_screening.py backend/pipeline.py backend/main.py backend/tests/test_regulatory_agent.py
git commit -m "feat(agent): real RAG retrieval in RegulatoryScreeningAgent"
```

---

## Task 9: Add frontend test infrastructure

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/vitest.config.js`
- Create: `frontend/src/test/setup.js`

- [ ] **Step 1: Update `frontend/package.json`**

```json
{
  "name": "eia-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/user-event": "^14.5.0",
    "@vitejs/plugin-react": "^4.3.4",
    "jsdom": "^25.0.0",
    "vite": "^6.0.0",
    "vitest": "^2.1.0"
  }
}
```

- [ ] **Step 2: Install the new dev deps**

Run: `cd frontend && npm install`
Expected: installs cleanly.

- [ ] **Step 3: Create `frontend/vitest.config.js`**

```js
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    css: false,
  },
})
```

- [ ] **Step 4: Create `frontend/src/test/setup.js`**

```js
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => {
  cleanup()
})
```

- [ ] **Step 5: Sanity-check Vitest runs**

Run: `cd frontend && npm test 2>&1 | tail -20`
Expected: "No test files found" — that's fine, it confirms vitest is wired up.

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.js frontend/src/test/setup.js
git commit -m "test: add Vitest + @testing-library/react infrastructure"
```

---

## Task 10: Frontend modal rewrite (drop zone, polling, progress, delete)

**Files:**
- Modify: `frontend/src/components/SourcesModal.jsx`
- Test: `frontend/src/components/SourcesModal.test.jsx`

- [ ] **Step 1: Create the failing test `frontend/src/components/SourcesModal.test.jsx`**

```jsx
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import SourcesModal from './SourcesModal.jsx'

const mkRow = (overrides = {}) => ({
  id: 'id-1',
  filename: 'NEPA-40CFR1500_1508.pdf',
  sha256: 'a'.repeat(64),
  size_bytes: 1_800_000,
  uploaded_at: '2026-04-09T20:00:00Z',
  status: 'ready',
  status_message: null,
  chunks_total: 247,
  chunks_embedded: 247,
  chunk_count: 247,
  sections_count: 9,
  parser_warnings: 0,
  embedding_dim: 768,
  embedding_started_at: '2026-04-09T20:00:00Z',
  embedding_finished_at: '2026-04-09T20:01:30Z',
  is_current: true,
  ...overrides,
})

beforeEach(() => {
  global.fetch = vi.fn()
})
afterEach(() => {
  vi.restoreAllMocks()
})

const mockListResponse = (sources) => {
  global.fetch.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ sources }),
  })
}

describe('SourcesModal', () => {
  it('renders loading state then empty', async () => {
    mockListResponse([])
    render(<SourcesModal onClose={() => {}} />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText(/no sources yet/i)).toBeInTheDocument()
    })
  })

  it('renders a ready row with chunk count and DELETE', async () => {
    mockListResponse([mkRow()])
    render(<SourcesModal onClose={() => {}} />)
    await waitFor(() => {
      expect(screen.getByText('NEPA-40CFR1500_1508.pdf')).toBeInTheDocument()
    })
    expect(screen.getByText(/247 chunks/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /delete/i })).toBeInTheDocument()
  })

  it('renders an embedding row with progress bar and counters', async () => {
    const row = mkRow({
      status: 'embedding',
      chunks_embedded: 87,
      chunks_total: 247,
    })
    mockListResponse([row])
    render(<SourcesModal onClose={() => {}} />)
    await waitFor(() => {
      expect(screen.getByText(/87 \/ 247/)).toBeInTheDocument()
    })
    const bar = screen.getByTestId('progress-bar-fill-id-1')
    // 87/247 = 0.352 → "35.2%"
    expect(bar.style.width).toMatch(/^35\./)
  })

  it('renders a failed row with status_message', async () => {
    mockListResponse([mkRow({
      status: 'failed',
      status_message: 'Not a NEPA-style PDF (no CFR sections detected)',
    })])
    render(<SourcesModal onClose={() => {}} />)
    await waitFor(() => {
      expect(screen.getByText(/no CFR sections/i)).toBeInTheDocument()
    })
  })

  it('drop zone: dropping a PDF calls upload endpoint', async () => {
    mockListResponse([])
    // Second fetch is the upload itself
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mkRow({ status: 'pending' }),
    })
    // Third fetch: refetch list after upload
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ sources: [mkRow({ status: 'pending' })] }),
    })

    render(<SourcesModal onClose={() => {}} />)
    await waitFor(() => screen.getByText(/no sources yet/i))

    const file = new File(['%PDF-1.4 fake'], 'test.pdf', { type: 'application/pdf' })
    const dropZone = screen.getByTestId('drop-zone')
    fireEvent.drop(dropZone, {
      dataTransfer: { files: [file], types: ['Files'] },
    })

    await waitFor(() => {
      const calls = global.fetch.mock.calls
      const uploadCall = calls.find(
        (c) => typeof c[1] === 'object' && c[1]?.method === 'POST'
      )
      expect(uploadCall).toBeTruthy()
      expect(uploadCall[0]).toMatch(/\/api\/regulations\/sources$/)
    })
  })

  it('drop zone: dropping a non-PDF shows an error and does NOT call upload', async () => {
    mockListResponse([])
    render(<SourcesModal onClose={() => {}} />)
    await waitFor(() => screen.getByText(/no sources yet/i))

    const file = new File(['hi'], 'foo.txt', { type: 'text/plain' })
    fireEvent.drop(screen.getByTestId('drop-zone'), {
      dataTransfer: { files: [file], types: ['Files'] },
    })

    await waitFor(() => {
      expect(screen.getByText(/must be a pdf/i)).toBeInTheDocument()
    })
    // Only the initial GET ran
    expect(global.fetch.mock.calls.length).toBe(1)
  })

  it('clicking DELETE sends DELETE and removes the row', async () => {
    mockListResponse([mkRow()])
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ deleted_chunks: 247 }),
    })
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ sources: [] }),
    })

    render(<SourcesModal onClose={() => {}} />)
    await waitFor(() => screen.getByText('NEPA-40CFR1500_1508.pdf'))
    fireEvent.click(screen.getByRole('button', { name: /delete/i }))
    fireEvent.click(screen.getByRole('button', { name: /confirm delete/i }))

    await waitFor(() => {
      expect(screen.queryByText('NEPA-40CFR1500_1508.pdf')).toBeNull()
    })
  })

  it('polls every 2s while a row is in embedding', async () => {
    vi.useFakeTimers()
    try {
      const embedding = mkRow({ status: 'embedding', chunks_embedded: 10, chunks_total: 100 })
      // initial fetch
      global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ sources: [embedding] }) })
      // poll fetch
      global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ sources: [embedding] }) })

      render(<SourcesModal onClose={() => {}} />)
      await waitFor(() => screen.getByText(/10 \/ 100/))

      const before = global.fetch.mock.calls.length
      await act(async () => {
        vi.advanceTimersByTime(2100)
      })
      expect(global.fetch.mock.calls.length).toBeGreaterThan(before)
    } finally {
      vi.useRealTimers()
    }
  })
})
```

- [ ] **Step 2: Run the test, expect failure**

Run: `cd frontend && npm test -- SourcesModal 2>&1 | tail -40`
Expected: many failures — the new modal doesn't exist yet.

- [ ] **Step 3: Replace `frontend/src/components/SourcesModal.jsx`**

```jsx
import { useEffect, useRef, useState, useCallback } from 'react'

const apiBase = import.meta.env.VITE_API_URL ?? ''
const POLL_INTERVAL_MS = 2000
const MAX_BYTES = 25 * 1024 * 1024

function formatBytes(n) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(2)} MB`
}

function formatEta(secs) {
  if (secs == null || !Number.isFinite(secs) || secs < 0) return ''
  if (secs < 60) return `~${Math.round(secs)}s`
  const m = Math.floor(secs / 60)
  const s = Math.round(secs % 60)
  return `~${m}m ${s}s`
}

function computeEta(row) {
  if (row.status !== 'embedding') return null
  if (!row.embedding_started_at || !row.chunks_total) return null
  if ((row.chunks_embedded ?? 0) < 5) return null
  const startedMs = Date.parse(row.embedding_started_at)
  const elapsedSec = Math.max(0.1, (Date.now() - startedMs) / 1000)
  const rate = row.chunks_embedded / elapsedSec
  if (rate <= 0) return null
  const remaining = row.chunks_total - row.chunks_embedded
  return remaining / rate
}

function isInFlight(row) {
  return row.status === 'pending' || row.status === 'embedding'
}

export default function SourcesModal({ onClose }) {
  const [sources, setSources] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [uploadError, setUploadError] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState(null)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef(null)
  const pollTimerRef = useRef(null)

  const fetchSources = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/regulations/sources`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setSources(data.sources || [])
      setError(null)
    } catch (e) {
      setError(e.message || 'Failed to load sources')
    } finally {
      setLoading(false)
    }
  }, [])

  // Initial load
  useEffect(() => { fetchSources() }, [fetchSources])

  // Polling while anything is in flight
  useEffect(() => {
    const anyInFlight = sources.some(isInFlight)
    if (!anyInFlight) {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
      return
    }
    if (pollTimerRef.current) return
    pollTimerRef.current = setInterval(fetchSources, POLL_INTERVAL_MS)
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [sources, fetchSources])

  // Close on Escape
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const validateFile = (file) => {
    if (!file) return 'No file selected'
    if (!file.name.toLowerCase().endsWith('.pdf') && file.type !== 'application/pdf') {
      return 'File must be a PDF'
    }
    if (file.size > MAX_BYTES) return `File too large (max ${MAX_BYTES / 1024 / 1024} MB)`
    return null
  }

  const uploadOne = async (file) => {
    const errMsg = validateFile(file)
    if (errMsg) {
      setUploadError(errMsg)
      return
    }
    setUploadError(null)
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('is_current', 'false')
      const res = await fetch(`${apiBase}/api/regulations/sources`, {
        method: 'POST',
        body: fd,
      })
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { detail = (await res.json()).detail || detail } catch {}
        throw new Error(detail)
      }
    } catch (e) {
      setUploadError(e.message || 'Upload failed')
    } finally {
      setUploading(false)
      fetchSources()
    }
  }

  const onFiles = async (fileList) => {
    const files = Array.from(fileList || [])
    for (const f of files) await uploadOne(f)
  }

  const onDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    onFiles(e.dataTransfer.files)
  }

  const onDelete = async (id) => {
    try {
      const res = await fetch(`${apiBase}/api/regulations/sources/${id}`, {
        method: 'DELETE',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
    } catch (e) {
      setError(e.message || 'Delete failed')
    } finally {
      setConfirmDeleteId(null)
      fetchSources()
    }
  }

  return (
    <div style={styles.backdrop} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div style={styles.header}>
          <span style={styles.title}>REGULATORY SOURCES</span>
          <button style={styles.closeBtn} onClick={onClose} title="Close">×</button>
        </div>

        <div
          data-testid="drop-zone"
          style={{ ...styles.dropZone, ...(dragOver ? styles.dropZoneActive : {}) }}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <div style={styles.dropIcon}>⇧</div>
          <div style={styles.dropTitle}>
            {uploading ? 'UPLOADING…' : 'DROP PDF HERE OR CLICK TO BROWSE'}
          </div>
          <div style={styles.dropHint}>
            NEPA-style regulatory documents only · max 25 MB
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            multiple
            style={{ display: 'none' }}
            onChange={(e) => onFiles(e.target.files)}
          />
        </div>

        {uploadError && <div style={styles.errorBanner}>{uploadError}</div>}

        <div style={styles.body}>
          {loading && <div style={styles.muted}>Loading sources…</div>}
          {error && <div style={styles.error}>Error: {error}</div>}
          {!loading && !error && sources.length === 0 && (
            <div style={styles.muted}>No sources yet. Drop a PDF above to begin.</div>
          )}

          {sources.map((row) => {
            const eta = computeEta(row)
            const pct = row.chunks_total
              ? Math.min(100, Math.max(0, (row.chunks_embedded / row.chunks_total) * 100))
              : 0
            const showConfirm = confirmDeleteId === row.id
            return (
              <div key={row.id} style={styles.row}>
                <div style={styles.rowMain}>
                  <div style={styles.fname}>
                    <span style={styles.statusDot(row.status)} />
                    {row.filename}
                  </div>
                  <div style={styles.meta}>
                    {formatBytes(row.size_bytes)}
                    {row.status === 'ready' && (
                      <> · <span style={styles.ready}>{row.chunk_count} chunks</span> · {row.sections_count} sections</>
                    )}
                    {row.status === 'embedding' && row.chunks_total != null && (
                      <> · {row.sections_count || '?'} sections detected</>
                    )}
                    {row.status === 'pending' && <> · queued</>}
                    {row.status === 'failed' && <> · <span style={styles.failed}>{row.status_message}</span></>}
                  </div>
                  {row.status === 'embedding' && row.chunks_total != null && (
                    <div style={styles.progressWrap}>
                      <div style={styles.progressBar}>
                        <div
                          data-testid={`progress-bar-fill-${row.id}`}
                          style={{ ...styles.progressFill, width: `${pct.toFixed(1)}%` }}
                        />
                      </div>
                      <div style={styles.progressText}>
                        {row.chunks_embedded} / {row.chunks_total} chunks
                        {eta != null && <> · {formatEta(eta)}</>}
                      </div>
                    </div>
                  )}
                </div>
                <div style={styles.rowActions}>
                  {showConfirm ? (
                    <>
                      <button
                        type="button"
                        style={styles.confirmBtn}
                        onClick={() => onDelete(row.id)}
                      >
                        CONFIRM DELETE
                      </button>
                      <button
                        type="button"
                        style={styles.cancelBtn}
                        onClick={() => setConfirmDeleteId(null)}
                      >
                        CANCEL
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      style={styles.deleteBtn}
                      onClick={() => setConfirmDeleteId(row.id)}
                      aria-label={`Delete ${row.filename}`}
                    >
                      DELETE
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        <div style={styles.footer}>
          <span style={styles.footerHint}>
            Embedding runs in the background.
          </span>
          <button style={styles.footerBtn} onClick={onClose}>CLOSE</button>
        </div>
      </div>
    </div>
  )
}

const dotColor = (status) => ({
  ready: 'var(--green-primary)',
  embedding: 'var(--green-primary)',
  pending: 'var(--text-muted)',
  failed: 'var(--red-alert)',
}[status] || 'var(--text-muted)')

const styles = {
  backdrop: {
    position: 'fixed', inset: 0,
    background: 'rgba(0, 0, 0, 0.7)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 1000, backdropFilter: 'blur(2px)',
  },
  modal: {
    width: 'min(680px, 92vw)', maxHeight: '88vh',
    background: 'var(--bg-secondary)',
    border: '1px solid var(--green-primary)',
    borderRadius: '8px',
    boxShadow: '0 0 30px rgba(0, 255, 100, 0.15)',
    display: 'flex', flexDirection: 'column', overflow: 'hidden',
  },
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '14px 18px',
    borderBottom: '1px solid var(--border)',
    background: 'var(--bg-card)',
  },
  title: {
    fontFamily: 'var(--font-mono)', fontSize: '12px',
    letterSpacing: '3px', color: 'var(--green-primary)',
  },
  closeBtn: {
    background: 'transparent', border: 'none',
    color: 'var(--text-muted)', fontSize: '22px',
    cursor: 'pointer', lineHeight: 1, padding: '0 4px',
  },
  dropZone: {
    margin: '14px 18px 0',
    padding: '18px',
    border: '2px dashed var(--border)',
    borderRadius: '6px',
    textAlign: 'center',
    cursor: 'pointer',
    transition: 'border-color 0.15s, background 0.15s',
  },
  dropZoneActive: {
    borderColor: 'var(--green-primary)',
    background: 'var(--green-dim)',
  },
  dropIcon: {
    fontSize: '20px', color: 'var(--green-primary)', marginBottom: '6px',
  },
  dropTitle: {
    fontFamily: 'var(--font-mono)', fontSize: '11px',
    letterSpacing: '2px', color: 'var(--text-primary)',
  },
  dropHint: {
    fontFamily: 'var(--font-mono)', fontSize: '9px',
    color: 'var(--text-muted)', marginTop: '4px',
  },
  errorBanner: {
    margin: '8px 18px 0', padding: '8px 12px',
    fontFamily: 'var(--font-mono)', fontSize: '10px',
    color: 'var(--red-alert)',
    border: '1px solid var(--red-alert)',
    borderRadius: '4px',
  },
  body: {
    padding: '14px 18px', overflowY: 'auto',
    display: 'flex', flexDirection: 'column', gap: '10px', flex: 1,
  },
  row: {
    display: 'flex', alignItems: 'flex-start', gap: '12px',
    padding: '12px 14px',
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: '6px',
  },
  rowMain: { flex: 1, minWidth: 0 },
  rowActions: {
    display: 'flex', flexDirection: 'column', gap: '6px', alignItems: 'flex-end',
  },
  fname: {
    fontFamily: 'var(--font-mono)', fontSize: '12px',
    color: 'var(--text-primary)', wordBreak: 'break-all',
    display: 'flex', alignItems: 'center', gap: '8px',
  },
  statusDot: (status) => ({
    display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
    background: dotColor(status),
    boxShadow: status === 'ready' ? '0 0 6px var(--green-primary)' : 'none',
    flexShrink: 0,
  }),
  meta: {
    fontFamily: 'var(--font-mono)', fontSize: '10px',
    color: 'var(--text-muted)', marginTop: '4px',
  },
  ready: { color: 'var(--green-primary)' },
  failed: { color: 'var(--red-alert)' },
  progressWrap: { marginTop: '8px' },
  progressBar: {
    width: '100%', height: '6px',
    background: 'var(--bg-primary)',
    border: '1px solid var(--border)',
    borderRadius: '3px', overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    background: 'var(--green-primary)',
    transition: 'width 0.6s ease',
  },
  progressText: {
    fontFamily: 'var(--font-mono)', fontSize: '9px',
    color: 'var(--text-secondary)', marginTop: '4px',
  },
  deleteBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '1px',
    color: 'var(--text-muted)', background: 'transparent',
    border: '1px solid var(--border)', borderRadius: '3px',
    padding: '4px 8px', cursor: 'pointer',
  },
  confirmBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '1px',
    color: 'var(--red-alert)', background: 'transparent',
    border: '1px solid var(--red-alert)', borderRadius: '3px',
    padding: '4px 8px', cursor: 'pointer',
  },
  cancelBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '1px',
    color: 'var(--text-muted)', background: 'transparent',
    border: '1px solid var(--border)', borderRadius: '3px',
    padding: '4px 8px', cursor: 'pointer',
  },
  footer: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '12px 18px',
    borderTop: '1px solid var(--border)',
    background: 'var(--bg-card)',
  },
  footerHint: {
    fontFamily: 'var(--font-mono)', fontSize: '9px',
    color: 'var(--text-muted)',
  },
  footerBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '1px',
    color: 'var(--text-secondary)', background: 'transparent',
    border: '1px solid var(--border)', borderRadius: '4px',
    padding: '6px 14px', cursor: 'pointer',
  },
  muted: {
    fontFamily: 'var(--font-mono)', fontSize: '11px',
    color: 'var(--text-muted)', fontStyle: 'italic',
    padding: '8px 0',
  },
  error: {
    fontFamily: 'var(--font-mono)', fontSize: '11px',
    color: 'var(--red-alert)', padding: '8px 0',
  },
}
```

- [ ] **Step 4: Run the modal tests**

Run: `cd frontend && npm test -- SourcesModal 2>&1 | tail -40`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SourcesModal.jsx frontend/src/components/SourcesModal.test.jsx
git commit -m "feat(frontend): rewrite SourcesModal with drop, polling, progress, delete"
```

---

## Task 11: Pin the VIEW SOURCES button regression

**Files:**
- Test: `frontend/src/components/AgentPipeline.test.jsx`

- [ ] **Step 1: Create the failing test `frontend/src/components/AgentPipeline.test.jsx`**

```jsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import AgentPipeline from './AgentPipeline.jsx'

beforeEach(() => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ sources: [] }),
  })
})
afterEach(() => {
  vi.restoreAllMocks()
})

const baseProps = {
  pipelineState: {
    project_parser: 'idle',
    environmental_data: 'idle',
    regulatory_screening: 'idle',
    impact_analysis: 'idle',
    report_synthesis: 'idle',
  },
  agentOutputs: {},
}

describe('AgentPipeline VIEW SOURCES button', () => {
  it('renders VIEW SOURCES on the regulatory_screening row', () => {
    render(<AgentPipeline {...baseProps} />)
    expect(screen.getByRole('button', { name: /view sources/i })).toBeInTheDocument()
  })

  it('does NOT render VIEW SOURCES on other rows', () => {
    render(<AgentPipeline {...baseProps} />)
    const buttons = screen.getAllByRole('button', { name: /view sources/i })
    expect(buttons).toHaveLength(1)
  })

  it('clicking VIEW SOURCES opens the modal', async () => {
    render(<AgentPipeline {...baseProps} />)
    fireEvent.click(screen.getByRole('button', { name: /view sources/i }))
    await waitFor(() => {
      expect(screen.getByText(/REGULATORY SOURCES/)).toBeInTheDocument()
    })
  })
})
```

- [ ] **Step 2: Run the test**

Run: `cd frontend && npm test -- AgentPipeline 2>&1 | tail -30`
Expected: all 3 tests PASS — the button code already exists in `AgentPipeline.jsx` from PR 14. This test pins the regression so a future refactor can't silently delete it.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AgentPipeline.test.jsx
git commit -m "test(frontend): pin VIEW SOURCES button regression"
```

---

## Task 12: Run the entire test suite end-to-end

- [ ] **Step 1: Backend full run**

Run: `cd backend && TEST_DATABASE_URL=$DATABASE_URL pytest tests/ -v`
Expected: every test passes. If any fail, fix them in place before continuing — do not move to the deploy step.

- [ ] **Step 2: Frontend full run**

Run: `cd frontend && npm test 2>&1 | tail -40`
Expected: every test passes.

- [ ] **Step 3: Build the frontend to confirm no production errors**

Run: `cd frontend && npm run build 2>&1 | tail -20`
Expected: build succeeds with no errors.

- [ ] **Step 4: Manual smoke (local)**

Run backend: `cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 5050`
Run frontend in another shell: `cd frontend && npm run dev`

Open `http://localhost:5173`. Confirm:
- [ ] Click REGULATORY SCREENING row → VIEW SOURCES button is visible.
- [ ] Click VIEW SOURCES → modal opens, lists the seed `NEPA-40CFR1500_1508.pdf` row (after the lifespan auto-import finishes).
- [ ] Drop a non-PDF → inline error appears, no upload happens.
- [ ] Drop a small NEPA-style test PDF → row appears immediately with EMBEDDING status, progress bar advances, ETA appears once `chunks_embedded >= 5`, settles to READY.
- [ ] DELETE → confirm prompt → row disappears.
- [ ] Run the full pipeline with the seed PDF ingested → REGULATORY SCREENING dropdown shows actual regulations (not "No regulations identified").

- [ ] **Step 5: Commit any fix-ups from manual smoke**

```bash
git add -p   # whatever you touched
git commit -m "fix: address smoke test findings"
```

(Skip if nothing needed.)

---

## Task 13: Deploy verification on Render

This task is mandatory because the original PR 14 frontend bundle is stale on the live deploy.

- [ ] **Step 1: Push the branch and open the PR**

```bash
git push -u origin <branch-name>
gh pr create --title "DB-backed regulatory sources + real RAG retrieval" --body "$(cat <<'EOF'
## Summary
- Replaces filesystem-glob source discovery with a Postgres regulatory_sources table (BYTEA-backed)
- Adds drag-and-drop upload, live embedding progress + ETA, and delete with chunk cascade
- Wires RegulatoryScreeningAgent to query regulatory_chunks for real (no more stub)
- Fixes the View Sources button being absent from the live Render bundle by adding regression tests + a forced redeploy

## Test plan
- [ ] backend pytest: parser, embedder, store, repo, ingest, api, agent
- [ ] frontend vitest: SourcesModal + AgentPipeline
- [ ] manual smoke on local (drop a PDF, watch progress, delete)
- [ ] deploy verification: confirm View Sources button visible on live Render URL

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Watch the Render dashboard build**

After the PR merges to main (or whichever branch Render auto-deploys from), open the Render dashboard and watch the build for both the backend and frontend services.

- [ ] **Step 3: If autoDeploy is off, trigger manually**

```bash
cat /Users/sanderschulman/Developer/aiagentsproject/render.yaml
```

If `autoDeploy: false` is set, log into Render and click "Manual Deploy → Clear build cache & deploy" on both services.

- [ ] **Step 4: Verify the live frontend has the new bundle**

Open `https://eiagentsproject.onrender.com` (or the actual URL) in an incognito window. In DevTools → Network → JS, confirm the served `index-*.js` file has a new hash compared to the previous deploy.

- [ ] **Step 5: Click through on the live deploy**

- [ ] VIEW SOURCES button visible on REGULATORY SCREENING row.
- [ ] Modal opens, lists seed PDF.
- [ ] Drop a small test PDF → progress bar advances.
- [ ] Run the pipeline → real regulations appear in the dropdown.

- [ ] **Step 6: If the button still does not appear**

Check the browser console for an error from `SourcesModal.jsx`. The most likely culprit is that `VITE_API_URL` isn't set in the deployed frontend env, so the polling fetch hits the wrong host. Fix by setting `VITE_API_URL` in the Render frontend service env vars and redeploying.

---

## Self-Review

**1. Spec coverage:** Walking through the spec sections:

- Goals 1–5 ✓ — covered by Tasks 5–8 (DB), 6+7 (upload+ingest), 7 (DB-backed registry), 8 (real RAG), 13 (deploy verification).
- Non-goals correctly omitted from tasks (no generic parser, no Celery, no WebSockets, no auth).
- Architecture diagram ✓ — Tasks 6–8 implement every box.
- Data model ✓ — Task 5 creates the table with every field listed in the spec, including `chunks_total`, `chunks_embedded`, `embedding_started_at`, `embedding_finished_at`, `is_current`.
- API surface ✓ — Task 7 implements GET list, GET one, POST upload, DELETE.
- Background ingestion ✓ — Task 6.
- One-time auto-import ✓ — Task 7 step 3 (lifespan addition).
- Frontend UI (drop zone, progress bar, ETA, polling, delete) ✓ — Task 10.
- RAG retrieval wiring ✓ — Task 8.
- Logging with correlation IDs ✓ — Task 6 + Task 8 (lambda log/warn/err helpers).
- Tests: backend repo, API, end-to-end, agent — Tasks 5, 7, 6, 8. Frontend modal + pipeline regression — Tasks 10, 11.
- Deploy verification ✓ — Task 13.

**2. Placeholder scan:** No TBDs, no "implement later", no "add appropriate error handling", no "similar to Task N". Each step has the actual code.

**3. Type consistency:**
- `regulatory_sources` field names match across Tasks 5, 6, 7, 10. (`chunks_total`, `chunks_embedded`, `chunk_count`, `embedding_started_at`, `embedding_finished_at`.)
- `insert_source(conn, *, filename, sha256, size_bytes, blob, is_current)` — same signature in Task 5 (definition), Task 6 (test fixture), Task 7 (API handler).
- `update_status(conn, id, *, status, ...)` — same kwargs across Tasks 5, 6.
- `ingest_source_sync(conn, *, source_id, embedding_provider, correlation_id=None)` — same in Task 6 (definition), Task 7 (background task).
- `RegulatoryScreeningAgent.__init__(self, llm, embedding_provider)` — same in Task 8 (definition), Task 8 step 4 (pipeline.py wiring), Task 8 tests.
- Frontend `progress-bar-fill-{id}` data-testid pattern matches between Task 10 modal and Task 10 tests.

No drift detected.

**4. Risks reminder:**
- Tests need a `TEST_DATABASE_URL` (or fall back to `DATABASE_URL`); the conftest skips cleanly if neither is set, but CI must set one for full coverage.
- The seed-PDF auto-import on first cold start adds 30–90s to startup. Acceptable but should be noted in the Render deploy logs check.
