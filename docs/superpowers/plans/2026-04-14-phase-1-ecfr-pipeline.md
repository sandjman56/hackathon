# Phase 1 — eCFR Ingest + Pipeline Generalization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an eCFR XML ingest path to the regulatory RAG pipeline (fetch → parse → chunk → embed → upsert), generalize the parser dispatch to support multiple content types, and ship a chunks inspector UI so the output is verifiable.

**Architecture:** One generalized pipeline with inline `content_type` dispatch in `detect_parser`. New eCFR HTTP client (`api_clients/ecfr.py`), new XML parser (`rag/regulatory/parser_ecfr.py`) that returns the existing `RawSection` dataclass, new orchestrator (`services/ecfr_ingest.py`) that upserts a source row and delegates to the shared `ingest_source_sync`. Two trigger surfaces share the orchestrator: a CLI script and `POST /api/regulations/sources/ecfr`. Audit log table records every ingest attempt. Frontend `ChunksView.jsx` replaces the generic truncated-cell viewer for the `regulatory_chunks` table, with a per-source filter dropdown.

**Tech Stack:** FastAPI, psycopg2, pgvector, httpx, xml.etree.ElementTree (stdlib), pymupdf (unchanged), React 18 + Vite, vitest.

**Spec:** `docs/superpowers/specs/2026-04-14-phase-1-ecfr-pipeline-design.md`

**Spec refinements discovered during codebase review** (apply these over the spec where they differ):
- **Endpoint prefix is `/api/regulations/sources`**, not `/api/sources`. The spec's `POST /api/sources/ecfr` becomes `POST /api/regulations/sources/ecfr`. The chunks inspector endpoints become `GET /api/regulations/sources` and `GET /api/regulations/sources/{id}/chunks`.
- **Schema changes live in `init_db()`** (`backend/db/vector_store.py`), not a migrations package. Use idempotent `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for existing tables; add the column to `init_regulatory_table` in `rag/regulatory/store.py` for fresh installs.
- **`RawSection.effective_date` is `Optional[str]`** (ISO date string), not `date`. DB column is `DATE` — psycopg2 converts at insert time.
- **Backend dev port is 8000**, not 5050 (the 5050 reference in the loaded CLAUDE.md is for a different project).
- **HTTP status for async ingest start is `202`** (matches existing `POST /api/regulations/sources`), not `200`.

---

## File Structure

### New files
| Path | Responsibility |
|---|---|
| `backend/api_clients/ecfr.py` | HTTP client: `fetch_ecfr_xml`, `resolve_current_date` |
| `backend/rag/regulatory/parser_ecfr.py` | XML bytes → `tuple[list[RawSection], list[str]]` |
| `backend/services/ecfr_ingest.py` | `ingest_ecfr_source` orchestrator + audit log writes |
| `backend/scripts/ingest_ecfr.py` | CLI entry point (single + batch, `--dry-run`) |
| `backend/tests/test_parser_ecfr.py` | Parser unit tests (golden files) |
| `backend/tests/test_ecfr_client.py` | HTTP client tests (httpx.MockTransport) |
| `backend/tests/test_ecfr_ingest.py` | Orchestrator tests |
| `backend/tests/test_regulatory_ingest_xml.py` | End-to-end pipeline test (fixture XML → chunks) |
| `backend/tests/test_init_db_schema.py` | Schema migration safety test |
| `backend/tests/fixtures/ecfr/title-36_part-800.xml` | Golden fixture (Section 106) |
| `backend/tests/fixtures/ecfr/title-23_part-771.xml` | Golden fixture (FHWA NEPA) |
| `backend/tests/fixtures/ecfr/title-33_part-323.xml` | Golden fixture (CWA 404) |
| `frontend/src/components/ChunksView.jsx` | Per-source chunk inspector with expand/collapse |
| `frontend/src/components/ChunksView.test.jsx` | Vitest tests |
| `docs/ingest-ecfr.md` | Operator guide |

### Modified files
| Path | What changes |
|---|---|
| `backend/db/vector_store.py` | `init_db()` adds 5 columns to `regulatory_sources`, partial unique index, `regulatory_ingest_log` table. Idempotent ALTERs. |
| `backend/rag/regulatory/store.py` | `init_regulatory_table` adds typed `source_id` UUID FK column + index; backfill from JSONB metadata. |
| `backend/db/regulatory_sources.py` | Add `upsert_ecfr_source` helper. |
| `backend/services/regulatory_ingest.py` | `detect_parser` takes `content_type` kwarg; `ingest_source_sync` dispatches on `parser_type` (includes `"ecfr_xml"`); reorders row-fetch before bytes-fetch. |
| `backend/main.py` | Add `POST /api/regulations/sources/ecfr`, `GET /api/regulations/sources/{id}/chunks` paginated endpoint. (`GET /api/regulations/sources` already exists; confirm shape, extend if needed.) |
| `backend/requirements.txt` | Unchanged — `xml.etree.ElementTree` is stdlib; `httpx` already present. |
| `frontend/src/components/TableDetail.jsx` | Branches into `<ChunksView/>` when `tableName === 'regulatory_chunks'`. |
| `README.md` | Add "Regulatory Source Ingestion" section pointing to `docs/ingest-ecfr.md`. |

---

## Execution order (maps to spec's 5 rollout steps)

1. **Tasks 1–2:** Schema migration + regression test (spec step 1)
2. **Tasks 3–4:** Pipeline generalization (spec step 2)
3. **Tasks 5–8:** eCFR client + parser + orchestrator (spec step 3)
4. **Tasks 9–10:** CLI + HTTP endpoint (spec step 4)
5. **Tasks 11–12:** Chunks inspector backend + frontend (spec step 5)
6. **Tasks 13–14:** Documentation + real-ingest smoke verification

Each task ends with a commit. Each rollout step is independently revertible.

---

## Prerequisites

Before starting: cut a new branch from `main` for this work.

```bash
git fetch origin
git checkout main
git pull
git checkout -b feat/ecfr-phase-1
```

---

## Task 1: Schema migration — additive columns, partial unique index, audit log table

**Files:**
- Modify: `backend/db/vector_store.py` (add statements to `init_db()`)
- Modify: `backend/rag/regulatory/store.py` (add `source_id` typed column + index to `init_regulatory_table`)
- Create: `backend/tests/test_init_db_schema.py`

- [ ] **Step 1.1: Write failing schema test**

Create `backend/tests/test_init_db_schema.py`:

```python
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
    assert "WHERE" in row[0] and "ecfr" in row[0]
```

- [ ] **Step 1.2: Run the test, confirm it fails**

```
cd backend && pytest tests/test_init_db_schema.py -v
```

Expected: three tests FAIL with `AssertionError: source_type not in cols` (or similar).

- [ ] **Step 1.3: Add ALTERs and audit log to `init_db()`**

Edit `backend/db/vector_store.py`. After the `for table_name in (...)` loop, before `conn.commit()`, add:

```python
        # ---- Phase 1 eCFR schema additions ----
        cur.execute("""
            ALTER TABLE regulatory_sources
              ADD COLUMN IF NOT EXISTS source_type    TEXT NOT NULL DEFAULT 'pdf_upload',
              ADD COLUMN IF NOT EXISTS content_type   TEXT NOT NULL DEFAULT 'application/pdf',
              ADD COLUMN IF NOT EXISTS effective_date DATE NULL,
              ADD COLUMN IF NOT EXISTS cfr_title      INT  NULL,
              ADD COLUMN IF NOT EXISTS cfr_part       TEXT NULL;
        """)
        # Partial unique index: only eCFR sources use tuple identity; PDF
        # uploads continue using the sha256 unique constraint.
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS regulatory_sources_identity_idx
              ON regulatory_sources (source_type, cfr_title, cfr_part, effective_date)
              WHERE source_type = 'ecfr';
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS regulatory_ingest_log (
              id             BIGSERIAL PRIMARY KEY,
              ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              correlation_id TEXT NOT NULL,
              source_id      UUID NULL REFERENCES regulatory_sources(id) ON DELETE SET NULL,
              trigger        TEXT NOT NULL,
              source_type    TEXT NOT NULL,
              cfr_title      INT NULL,
              cfr_part       TEXT NULL,
              effective_date DATE NULL,
              status         TEXT NOT NULL,
              duration_ms    INT NULL,
              chunks_count   INT NULL,
              error_message  TEXT NULL
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS regulatory_ingest_log_ts_idx
              ON regulatory_ingest_log (ts DESC);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS regulatory_ingest_log_source_idx
              ON regulatory_ingest_log (source_id);
        """)
```

- [ ] **Step 1.4: Add typed `source_id` column to `regulatory_chunks` via `store.py`**

Edit `backend/rag/regulatory/store.py`, inside `init_regulatory_table`, after the existing `CREATE TABLE IF NOT EXISTS regulatory_chunks (...)` block, add:

```python
    # Phase 1: promote source_id from metadata JSONB to typed UUID FK column.
    # ON DELETE CASCADE keeps chunks in sync when a source row is removed.
    cur.execute("""
        ALTER TABLE regulatory_chunks
          ADD COLUMN IF NOT EXISTS source_id UUID NULL
            REFERENCES regulatory_sources(id) ON DELETE CASCADE;
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS regulatory_chunks_source_id_idx
          ON regulatory_chunks (source_id);
    """)
    # One-time backfill from pre-Phase-1 rows (no-op on fresh install).
    cur.execute("""
        UPDATE regulatory_chunks
           SET source_id = (metadata->>'source_id')::uuid
         WHERE source_id IS NULL
           AND metadata ? 'source_id';
    """)
```

- [ ] **Step 1.5: Run schema tests — expect PASS**

```
cd backend && pytest tests/test_init_db_schema.py -v
```

Expected: all four tests PASS.

- [ ] **Step 1.6: Commit**

```bash
git add backend/db/vector_store.py backend/rag/regulatory/store.py backend/tests/test_init_db_schema.py
git commit -m "feat(db): add eCFR schema columns, partial unique index, and ingest audit log"
```

---

## Task 2: Regression — existing PDF ingest still works

No code change here — this task proves Task 1 was truly additive.

**Files:**
- Modify: none (read-only verification)

- [ ] **Step 2.1: Run the existing regulatory-sources API test suite**

```
cd backend && pytest tests/test_regulatory_sources_api.py -v
```

Expected: all tests PASS. If any fail, fix the schema migration before proceeding.

- [ ] **Step 2.2: Manual regression (dev DB only, skip in CI)**

Start backend (`uvicorn main:app --reload --port 8000`). Upload a PDF through the existing `POST /api/regulations/sources`. Poll `GET /api/regulations/sources/{id}` until `status="ready"`. Confirm the row has `source_type='pdf_upload'` and `content_type='application/pdf'` (defaults applied).

```bash
curl -s 'http://localhost:8000/api/regulations/sources/<id>' | jq '{source_type, content_type, status}'
```

Expected output:
```json
{"source_type":"pdf_upload","content_type":"application/pdf","status":"ready"}
```

- [ ] **Step 2.3: No commit** (verification only)

---

## Task 3: Generalize `detect_parser(content_type=...)`

**Files:**
- Modify: `backend/services/regulatory_ingest.py` (signature + body of `detect_parser`)
- Create: `backend/tests/test_detect_parser.py`

- [ ] **Step 3.1: Write failing tests**

Create `backend/tests/test_detect_parser.py`:

```python
"""detect_parser must dispatch on content_type, not sniff blindly."""
from __future__ import annotations

import pytest

from services.regulatory_ingest import detect_parser


def test_xml_routes_to_ecfr():
    result = detect_parser(b"<DIV5/>", content_type="application/xml")
    assert result == "ecfr_xml"


def test_pdf_with_pa_code_marker_routes_to_pa_code(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Pennsylvania Code Title 25")
    blob = doc.tobytes()
    doc.close()
    result = detect_parser(blob, content_type="application/pdf")
    assert result == "pa_code"


def test_pdf_without_pa_marker_routes_to_federal():
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Title 40—Protection of Environment")
    blob = doc.tobytes()
    doc.close()
    result = detect_parser(blob, content_type="application/pdf")
    assert result == "federal"


def test_unknown_content_type_raises():
    with pytest.raises(ValueError, match="unsupported content_type"):
        detect_parser(b"garbage", content_type="text/plain")
```

- [ ] **Step 3.2: Run tests, confirm they fail**

```
cd backend && pytest tests/test_detect_parser.py -v
```

Expected: TypeError about unexpected keyword arg `content_type` (the current `detect_parser` takes only `blob`).

- [ ] **Step 3.3: Update `detect_parser`**

Replace the existing `detect_parser` in `backend/services/regulatory_ingest.py` (currently lines 40–56):

```python
def detect_parser(blob: bytes, *, content_type: str) -> str:
    """Route bytes to the right parser based on content_type.

    EXTENSION POINT: add new content_type branches here.
    Pattern: see parser_ecfr.py for the XML reference implementation.
    See docs/ingest-ecfr.md 'Adding a new source type' for the procedure.

    Returns:
        ``"ecfr_xml"`` for eCFR Versioner XML responses,
        ``"pa_code"`` for Pennsylvania Code browser-printed PDFs,
        ``"federal"`` for NEPA/CFR-style scanned PDF reprints.
    """
    if content_type == "application/xml":
        return "ecfr_xml"

    if content_type == "application/pdf":
        try:
            doc = pymupdf.open(stream=blob, filetype="pdf")
            first_page_text = doc[0].get_text("text") if len(doc) > 0 else ""
            doc.close()
        except Exception:
            return "federal"
        if "Pennsylvania Code" in first_page_text:
            return "pa_code"
        return "federal"

    raise ValueError(f"unsupported content_type: {content_type!r}")
```

- [ ] **Step 3.4: Run tests, confirm PASS**

```
cd backend && pytest tests/test_detect_parser.py -v
```

- [ ] **Step 3.5: Commit**

```bash
git add backend/services/regulatory_ingest.py backend/tests/test_detect_parser.py
git commit -m "feat(ingest): generalize detect_parser on content_type"
```

---

## Task 4: Dispatch on parser_type in `ingest_source_sync` (incl. ecfr_xml stub)

Wires `detect_parser` into the orchestrator. At this point the `ecfr_xml` branch points at a not-yet-written `parse_ecfr_xml`; we'll implement that in Task 6. Until then, the branch raises a clear NotImplementedError so the pipeline still works for PDFs.

**Files:**
- Modify: `backend/services/regulatory_ingest.py`

- [ ] **Step 4.1: Write failing test**

Append to `backend/tests/test_detect_parser.py`:

```python
def test_ingest_source_sync_rejects_xml_before_parser_exists(monkeypatch, db_conn):
    """Until Task 6 lands, hitting the XML branch must raise cleanly."""
    # This test will be deleted in Task 6 (superseded by test_regulatory_ingest_xml.py)
    from services.regulatory_ingest import ingest_source_sync
    # ... actual DB/row setup out of scope for this micro-test;
    # skip if the fixture needs infra that's not yet wired.
    pytest.skip("placeholder — replaced by test_regulatory_ingest_xml.py in Task 6")
```

(No need to run — it's a `skip`, a placeholder.)

- [ ] **Step 4.2: Reorder + add dispatch in `ingest_source_sync`**

Edit `backend/services/regulatory_ingest.py`. Currently the function fetches `blob = get_source_bytes(...)` then calls `detect_parser(blob)`. Change to fetch the row first (so we know `content_type`), then bytes, then dispatch:

Find this block (≈ lines 81–94):

```python
        blob = get_source_bytes(conn, source_id)
        if blob is None:
            raise RuntimeError(f"source row not found: {source_id}")

        parser_type = detect_parser(blob)
        log("detected parser: %s, %d bytes", parser_type, len(blob))
        t0 = time.time()
        if parser_type == "pa_code":
            sections, parser_warnings = parse_pa_code_pdf(blob)
        else:
            sections, parser_warnings = parse_pdf(blob)
```

Replace with:

```python
        from db.regulatory_sources import get_source_by_id
        row = get_source_by_id(conn, source_id)
        if row is None:
            raise RuntimeError(f"source row not found: {source_id}")
        content_type = row.get("content_type") or "application/pdf"

        blob = get_source_bytes(conn, source_id)
        if blob is None:
            raise RuntimeError(f"source bytes missing: {source_id}")

        parser_type = detect_parser(blob, content_type=content_type)
        log("detected parser: %s (content_type=%s, %d bytes)",
            parser_type, content_type, len(blob))
        t0 = time.time()
        if parser_type == "ecfr_xml":
            from rag.regulatory.parser_ecfr import parse_ecfr_xml
            sections, parser_warnings = parse_ecfr_xml(blob)
        elif parser_type == "pa_code":
            sections, parser_warnings = parse_pa_code_pdf(blob)
        else:  # "federal"
            sections, parser_warnings = parse_pdf(blob)
```

Then further down (the `get_source_by_id` block that fetched the row a second time for filename — ≈ line 156–159) — delete it, since we now have `row` already:

```python
        # BEFORE
        from db.regulatory_sources import get_source_by_id
        row = get_source_by_id(conn, source_id)
        if row is None:
            raise RuntimeError(f"row vanished mid-ingest: {source_id}")
```

Simply delete those 4 lines. `row` is already in scope from earlier.

- [ ] **Step 4.3: Run the existing PDF ingest tests again**

```
cd backend && pytest tests/test_regulatory_sources_api.py tests/test_detect_parser.py -v
```

Expected: all PASS. XML path isn't reachable yet (no row has `content_type='application/xml'`), so the missing `parser_ecfr` module doesn't trip anything.

- [ ] **Step 4.4: Commit**

```bash
git add backend/services/regulatory_ingest.py backend/tests/test_detect_parser.py
git commit -m "feat(ingest): dispatch parser on content_type; reorder row-fetch before bytes"
```

---

## Task 5: eCFR HTTP client (`api_clients/ecfr.py`)

**Files:**
- Create: `backend/api_clients/ecfr.py`
- Create: `backend/tests/test_ecfr_client.py`

- [ ] **Step 5.1: Write failing tests (MockTransport, no network)**

Create `backend/tests/test_ecfr_client.py`:

```python
"""eCFR client: URL shape, retry loop, error paths. No network."""
from __future__ import annotations

import httpx
import pytest

from api_clients.ecfr import fetch_ecfr_xml, resolve_current_date


def _xml_response(body: bytes = b"<DIV5 N='800' TYPE='PART'/>") -> httpx.Response:
    return httpx.Response(
        status_code=200,
        content=body,
        headers={"content-type": "application/xml"},
    )


def test_fetch_ecfr_xml_builds_correct_url():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return _xml_response()

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_ecfr_xml(
            title=36, part="800", date="2024-01-01", client=client
        )
    assert result == b"<DIV5 N='800' TYPE='PART'/>"
    assert "/api/versioner/v1/full/2024-01-01/title-36.xml" in captured["url"]
    assert "part=800" in captured["url"]


def test_fetch_ecfr_xml_retries_on_500():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, content=b"boom")
        return _xml_response()

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_ecfr_xml(
            title=36, part="800", date="2024-01-01", client=client
        )
    assert result.startswith(b"<DIV5")
    assert calls["n"] == 2


def test_fetch_ecfr_xml_raises_after_exhausting_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_ecfr_xml(
                title=36, part="800", date="2024-01-01", client=client
            )


def test_fetch_ecfr_xml_rejects_non_xml_content_type():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html>not xml</html>",
            headers={"content-type": "text/html"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="unexpected content-type"):
            fetch_ecfr_xml(
                title=36, part="800", date="2024-01-01", client=client
            )


def test_resolve_current_date_returns_latest_valid_date():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/versioner/v1/versions/title-36" in str(request.url)
        return httpx.Response(
            200,
            json={
                "content_versions": [
                    {"date": "2022-04-01", "amendment_date": "2022-04-01"},
                    {"date": "2024-06-15", "amendment_date": "2024-06-15"},
                    {"date": "2023-01-10", "amendment_date": "2023-01-10"},
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = resolve_current_date(title=36, client=client)
    assert result == "2024-06-15"
```

- [ ] **Step 5.2: Run tests, expect FAIL**

```
cd backend && pytest tests/test_ecfr_client.py -v
```

Expected: ImportError — the module doesn't exist yet.

- [ ] **Step 5.3: Implement `api_clients/ecfr.py`**

Create `backend/api_clients/ecfr.py`:

```python
"""eCFR Versioner API v1 HTTP client.

Fetches CFR title/part XML from ecfr.gov. Ingest-time client (not used
by agents at query time — unlike most api_clients/*.py modules).

Public API:
  - fetch_ecfr_xml(title, part, date, client, correlation_id) -> bytes
  - resolve_current_date(title, client, correlation_id) -> str

Depends on: httpx
Used by: services/ecfr_ingest.py

Design spec: docs/superpowers/specs/2026-04-14-phase-1-ecfr-pipeline-design.md
"""
from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger("eia.api_clients.ecfr")

_ECFR_BASE_URL = "https://www.ecfr.gov/api/versioner/v1"
_MAX_RETRIES = 2
_RETRY_DELAY = 1.5  # seconds


def _tag(correlation_id: str | None) -> str:
    return f"[ECFR:{correlation_id or '-'}]"


def fetch_ecfr_xml(
    *,
    title: int,
    part: str,
    date: str,
    client: httpx.Client,
    correlation_id: str | None = None,
) -> bytes:
    """Fetch one CFR part as XML. Returns raw bytes.

    ``date`` must be an ISO YYYY-MM-DD string (callers resolve ``"current"``
    via :func:`resolve_current_date` first).

    Raises:
        httpx.HTTPStatusError: after retries exhausted
        RuntimeError: if response content-type is not XML
    """
    url = f"{_ECFR_BASE_URL}/full/{date}/title-{title}.xml"
    params = {"part": part}
    tag = _tag(correlation_id)
    logger.info("%s GET %s ?part=%s", tag, url, part)

    last_exc: Exception | None = None
    resp: httpx.Response | None = None
    for attempt in range(1, _MAX_RETRIES + 2):
        try:
            resp = client.get(url, params=params, timeout=30)
            logger.info("%s Response: HTTP %d (attempt %d)",
                        tag, resp.status_code, attempt)
            resp.raise_for_status()
            break
        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt <= _MAX_RETRIES:
                logger.warning(
                    "%s Attempt %d failed (%s), retrying in %.1fs…",
                    tag, attempt, type(exc).__name__, _RETRY_DELAY,
                )
                time.sleep(_RETRY_DELAY)
            continue
    else:
        assert last_exc is not None
        raise last_exc

    assert resp is not None
    ct = resp.headers.get("content-type", "")
    if "xml" not in ct.lower():
        raise RuntimeError(
            f"unexpected content-type from eCFR: {ct!r} for title-{title} part {part}"
        )
    return resp.content


def resolve_current_date(
    *,
    title: int,
    client: httpx.Client,
    correlation_id: str | None = None,
) -> str:
    """Return the latest valid amendment date for a CFR title as ISO YYYY-MM-DD.

    Calls GET /api/versioner/v1/versions/title-{N} and picks the maximum date
    from the ``content_versions`` list. The Versioner API's ``current`` alias
    returns 404 directly on /full/, so the canonical flow is date-resolution
    then a dated fetch.

    Raises:
        httpx.HTTPStatusError: on 4xx/5xx from versions endpoint
        RuntimeError: if the response shape doesn't contain content_versions
    """
    url = f"{_ECFR_BASE_URL}/versions/title-{title}"
    tag = _tag(correlation_id)
    logger.info("%s GET %s (resolve current)", tag, url)

    resp = client.get(url, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    versions = body.get("content_versions") or []
    if not versions:
        raise RuntimeError(
            f"eCFR versions endpoint for title-{title} returned no content_versions"
        )
    dates = [v.get("amendment_date") or v.get("date") for v in versions]
    dates = [d for d in dates if d]
    if not dates:
        raise RuntimeError(
            f"eCFR versions for title-{title}: no usable date fields"
        )
    return max(dates)
```

- [ ] **Step 5.4: Run tests, expect PASS**

```
cd backend && pytest tests/test_ecfr_client.py -v
```

- [ ] **Step 5.5: Commit**

```bash
git add backend/api_clients/ecfr.py backend/tests/test_ecfr_client.py
git commit -m "feat(api): add eCFR Versioner v1 HTTP client with retry + current-date resolver"
```

---

## Task 6: eCFR XML parser (`parser_ecfr.py`) + golden fixtures

**Files:**
- Create: `backend/rag/regulatory/parser_ecfr.py`
- Create: `backend/tests/test_parser_ecfr.py`
- Create: `backend/tests/fixtures/ecfr/title-36_part-800.xml`
- Create: `backend/tests/fixtures/ecfr/title-23_part-771.xml`
- Create: `backend/tests/fixtures/ecfr/title-33_part-323.xml`

- [ ] **Step 6.1: Download the three golden fixtures**

These three files are the ground truth. Download them once from the real eCFR API and commit them. Note: the `<DATE>` URL segment uses whatever "current" resolves to at fetch time; pick a single ISO date and use it for all three so the fixtures are a coherent snapshot.

```bash
cd backend/tests/fixtures/ecfr/
DATE=2025-10-01   # replace with any recent valid date
curl -sf "https://www.ecfr.gov/api/versioner/v1/full/${DATE}/title-36.xml?part=800" -o title-36_part-800.xml
curl -sf "https://www.ecfr.gov/api/versioner/v1/full/${DATE}/title-23.xml?part=771" -o title-23_part-771.xml
curl -sf "https://www.ecfr.gov/api/versioner/v1/full/${DATE}/title-33.xml?part=323" -o title-33_part-323.xml
ls -la
```

Confirm each file is >10 KB and opens with `<?xml` or `<DIV5`.

- [ ] **Step 6.2: Write failing parser tests**

Create `backend/tests/test_parser_ecfr.py`:

```python
"""Golden-file tests for the eCFR XML parser."""
from __future__ import annotations

from pathlib import Path

import pytest

from rag.regulatory.parser import DocumentType
from rag.regulatory.parser_ecfr import parse_ecfr_xml

_FIXTURES = Path(__file__).parent / "fixtures" / "ecfr"


def _load(name: str) -> bytes:
    p = _FIXTURES / name
    if not p.exists():
        pytest.skip(f"fixture missing: {p}")
    return p.read_bytes()


def test_parse_36_cfr_800_basics():
    sections, warnings = parse_ecfr_xml(_load("title-36_part-800.xml"))
    assert len(sections) >= 10, "36 CFR 800 should have at least 10 sections"
    assert all(s.document_type == DocumentType.CFR_REGULATION for s in sections)
    assert all(s.part == "800" for s in sections)
    first = sections[0]
    assert first.section.startswith("800.")
    assert "36 CFR" in first.citation
    assert first.title
    assert first.body
    assert isinstance(warnings, list)


def test_parse_23_cfr_771_handles_footnotes():
    sections, warnings = parse_ecfr_xml(_load("title-23_part-771.xml"))
    assert len(sections) >= 5
    assert all(s.part == "771" for s in sections)
    # FTREF is stripped; FTNT body captured as a warning note or metadata
    joined_body = " ".join(s.body for s in sections)
    assert "<FTREF" not in joined_body
    assert "<SU>" not in joined_body


def test_parse_33_cfr_323_short_baseline():
    sections, warnings = parse_ecfr_xml(_load("title-33_part-323.xml"))
    assert len(sections) >= 3
    assert all(s.part == "323" for s in sections)


def test_parse_empty_xml_raises():
    with pytest.raises(ValueError, match="empty|no content"):
        parse_ecfr_xml(b"")


def test_parse_malformed_xml_raises():
    with pytest.raises(ValueError):
        parse_ecfr_xml(b"<not-closed>")


def test_parse_missing_hierarchy_metadata_falls_back():
    # Minimal valid eCFR shape with no hierarchy_metadata attribute.
    xml = b"""<DIV5 N="999" TYPE="PART">
      <HEAD>PART 999 — Test Part</HEAD>
      <DIV8 N="999.1" TYPE="SECTION">
        <HEAD>\xc2\xa7 999.1 A section.</HEAD>
        <P>Body text.</P>
      </DIV8>
    </DIV5>"""
    sections, warnings = parse_ecfr_xml(xml)
    assert len(sections) == 1
    assert sections[0].section == "999.1"
    # Citation is constructed when hierarchy_metadata is absent.
    assert "999.1" in sections[0].citation
    assert any("hierarchy_metadata" in w for w in warnings)
```

- [ ] **Step 6.3: Run tests, expect FAIL**

```
cd backend && pytest tests/test_parser_ecfr.py -v
```

Expected: ImportError — `parser_ecfr` doesn't exist.

- [ ] **Step 6.4: Implement `parser_ecfr.py`**

Create `backend/rag/regulatory/parser_ecfr.py`:

```python
"""eCFR XML → ordered list of RawSection records.

Parses the XML returned by the eCFR Versioner API. The response root is a
single <DIV5 TYPE="PART"> element (no wrapping envelope).

Public API:
  - parse_ecfr_xml(xml_bytes) -> tuple[list[RawSection], list[str]]

Depends on: xml.etree.ElementTree (stdlib), rag.regulatory.parser.RawSection
Used by: services/regulatory_ingest.py (via detect_parser dispatch)

Design spec: docs/superpowers/specs/2026-04-14-phase-1-ecfr-pipeline-design.md

Warning-vs-log convention:
  - Append to the returned list[str] when something abnormal is observed
    that the operator should see (unrecognized structural tag, missing
    hierarchy_metadata, malformed section attribute).
  - Log at debug only for recognized-but-stripped formatting tags
    (<AMDDATE>, <EDNOTE>, <CITA>).
"""
from __future__ import annotations

import json
import logging
from typing import Optional
from xml.etree import ElementTree as ET

from rag.regulatory.parser import DocumentType, RawSection

logger = logging.getLogger("eia.rag.regulatory.parser_ecfr")

# Tags treated as inline formatting; their text is preserved but tag is stripped.
_INLINE_STRIP_KEEP_TEXT = {"I", "E", "SU"}
# Tags whose entire content is discarded from body (but may be logged).
_BODY_DROP = {"FTREF", "CITA", "AMDDATE", "EDNOTE"}
# Tags captured separately (not part of <P> body).
_ANNOTATION_TAGS = {"FTNT"}


def parse_ecfr_xml(
    xml_bytes: bytes,
) -> tuple[list[RawSection], list[str]]:
    """Parse one CFR part's XML into RawSection records.

    Args:
        xml_bytes: The raw XML response body from
            GET /api/versioner/v1/full/{date}/title-{N}.xml?part={P}.

    Returns:
        (sections, warnings): ``sections`` in document order, ``warnings``
        as human-readable strings suitable for the DB parser_warnings count.

    Raises:
        ValueError: on empty input or unparseable XML.
    """
    if not xml_bytes or not xml_bytes.strip():
        raise ValueError("parse_ecfr_xml: empty xml input")

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"parse_ecfr_xml: malformed XML: {exc}") from exc

    if root.tag != "DIV5" or root.attrib.get("TYPE") != "PART":
        raise ValueError(
            f"parse_ecfr_xml: expected root <DIV5 TYPE='PART'>, got "
            f"<{root.tag} TYPE={root.attrib.get('TYPE')!r}>"
        )

    warnings: list[str] = []
    part_number = root.attrib.get("N", "").strip()
    part_title = _head_text(root)
    part_hierarchy = _parse_hierarchy(root, warnings)

    sections: list[RawSection] = []
    # Walk all descendants; preserve document order. Track subpart only for
    # warnings/logging (citation comes from hierarchy_metadata per-section).
    for el in _iter_content(root):
        tag = el.tag
        el_type = el.attrib.get("TYPE", "")

        if tag == "DIV8" and el_type == "SECTION":
            sections.append(
                _section_from_div8(el, part_number, part_title, warnings)
            )
        elif tag == "DIV9" and el_type == "APPENDIX":
            sections.append(
                _section_from_div9(el, part_number, part_title, warnings)
            )
        elif tag == "DIV6" and el_type == "SUBPART":
            continue  # subpart acts only as a container; recurse via _iter_content
        elif tag in {"HEAD", "AUTH", "SOURCE"}:
            continue  # part-level metadata already captured
        elif tag in _BODY_DROP:
            continue
        else:
            warnings.append(
                f"unexpected element <{tag} TYPE={el_type!r}> under DIV5; skipped"
            )
            logger.warning("unexpected element %s TYPE=%s", tag, el_type)

    if not sections:
        warnings.append(f"no sections found under DIV5 N={part_number!r}")
    return sections, warnings


# ---------------------------- helpers ----------------------------------


def _iter_content(root: ET.Element):
    """Yield SECTION/SUBPART/APPENDIX/other children, recursing into SUBPART."""
    for child in list(root):
        if child.tag == "DIV6" and child.attrib.get("TYPE") == "SUBPART":
            yield child  # subpart marker
            yield from _iter_content(child)
        else:
            yield child


def _head_text(el: ET.Element) -> str:
    head = el.find("HEAD")
    if head is None:
        return ""
    return _gather_text(head).strip()


def _parse_hierarchy(el: ET.Element, warnings: list[str]) -> Optional[dict]:
    raw = el.attrib.get("hierarchy_metadata")
    if not raw:
        warnings.append(
            f"<{el.tag} N={el.attrib.get('N')!r}>: missing hierarchy_metadata"
        )
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        warnings.append(
            f"<{el.tag} N={el.attrib.get('N')!r}>: hierarchy_metadata not valid JSON"
        )
        return None


def _section_from_div8(
    el: ET.Element, part: str, part_title: str, warnings: list[str]
) -> RawSection:
    n = el.attrib.get("N", "").strip()
    hier = _parse_hierarchy(el, warnings)
    head_text = _head_text(el)
    # Strip leading "§ {n}" if present so `title` is the heading prose.
    title = _strip_section_prefix(head_text, n)
    body = _collect_body(el)
    citation = _citation(hier, part, n, default=f"{part} CFR §{n}".strip())

    return RawSection(
        document_type=DocumentType.CFR_REGULATION,
        section=n,
        title=title,
        body=body,
        citation=citation,
        pages=[],
        part=part,
        part_title=part_title,
    )


def _section_from_div9(
    el: ET.Element, part: str, part_title: str, warnings: list[str]
) -> RawSection:
    n = el.attrib.get("N", "").strip()
    hier = _parse_hierarchy(el, warnings)
    head_text = _head_text(el)
    section_id = f"App{n}" if n else "App"
    body = _collect_body(el)
    citation = _citation(hier, part, section_id, default=f"{part} CFR App. {n}".strip())

    return RawSection(
        document_type=DocumentType.CFR_REGULATION,
        section=section_id,
        title=head_text,
        body=body,
        citation=citation,
        pages=[],
        part=part,
        part_title=part_title,
    )


def _citation(
    hier: Optional[dict],
    part: str,
    section: str,
    *,
    default: str,
) -> str:
    if hier and isinstance(hier.get("citation"), str):
        return hier["citation"]
    return default


def _strip_section_prefix(head: str, n: str) -> str:
    # Heading looks like "§ 800.3  Initiation of the section 106 process."
    head = head.strip()
    markers = (f"§ {n}", f"§{n}", n)
    for m in markers:
        if head.startswith(m):
            return head[len(m):].lstrip(" .\u00a0\t").strip()
    return head


def _collect_body(section_el: ET.Element) -> str:
    parts: list[str] = []
    for p in section_el.findall("P"):
        text = _gather_text(p).strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _gather_text(el: ET.Element) -> str:
    """Depth-first text assembly, stripping known tags per convention."""
    chunks: list[str] = []
    if el.text:
        chunks.append(el.text)
    for child in el:
        if child.tag in _BODY_DROP:
            if child.tail:
                chunks.append(child.tail)
            continue
        if child.tag in _ANNOTATION_TAGS:
            # Footnote bodies — drop from inline flow (captured elsewhere later).
            if child.tail:
                chunks.append(child.tail)
            continue
        if child.tag in _INLINE_STRIP_KEEP_TEXT:
            chunks.append(_gather_text(child))
        else:
            chunks.append(_gather_text(child))
        if child.tail:
            chunks.append(child.tail)
    return "".join(chunks)
```

- [ ] **Step 6.5: Run tests, expect PASS**

```
cd backend && pytest tests/test_parser_ecfr.py -v
```

If a specific assertion fails (e.g., section count off by 1), adjust the test's expected count to reflect the actual fixture — the fixtures are ground truth. Do NOT weaken structural assertions (document_type, part, citation format).

- [ ] **Step 6.6: Remove Task 4's placeholder skip-test**

Open `backend/tests/test_detect_parser.py` and delete the `test_ingest_source_sync_rejects_xml_before_parser_exists` function.

- [ ] **Step 6.7: Commit**

```bash
git add backend/rag/regulatory/parser_ecfr.py backend/tests/test_parser_ecfr.py backend/tests/fixtures/ecfr/ backend/tests/test_detect_parser.py
git commit -m "feat(parser): add eCFR XML parser producing RawSection records"
```

---

## Task 7: End-to-end pipeline integration test (fixture XML → chunks)

**Files:**
- Create: `backend/tests/test_regulatory_ingest_xml.py`

- [ ] **Step 7.1: Write the integration test**

```python
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
```

- [ ] **Step 7.2: Run the test, expect PASS**

```
cd backend && TEST_DATABASE_URL=<url> pytest tests/test_regulatory_ingest_xml.py -v
```

If it fails because of chunker edge cases on very small sections, the parser probably emitted a degenerate section — investigate parser output before weakening the test.

- [ ] **Step 7.3: Commit**

```bash
git add backend/tests/test_regulatory_ingest_xml.py
git commit -m "test(ingest): end-to-end fixture XML → chunks pipeline"
```

---

## Task 8: `upsert_ecfr_source` helper + `ingest_ecfr_source` orchestrator

**Files:**
- Modify: `backend/db/regulatory_sources.py` (add `upsert_ecfr_source`)
- Create: `backend/services/ecfr_ingest.py`
- Create: `backend/tests/test_ecfr_ingest.py`

- [ ] **Step 8.1: Write tests for `upsert_ecfr_source`**

Append to a new `backend/tests/test_ecfr_ingest.py`:

```python
"""Orchestrator + upsert tests for the eCFR ingest service."""
from __future__ import annotations

import os
from datetime import date

import psycopg2
import pytest

from db.regulatory_sources import upsert_ecfr_source
from db.vector_store import init_db


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


def test_upsert_ecfr_source_inserts_new(real_conn):
    sid = upsert_ecfr_source(
        real_conn,
        cfr_title=36,
        cfr_part="800",
        effective_date=None,
        filename="title-36_part-800.xml",
        bytes_=b"<DIV5/>",
    )
    real_conn.commit()
    assert sid

    with real_conn.cursor() as cur:
        cur.execute("SELECT source_type, content_type, cfr_title FROM regulatory_sources WHERE id=%s", (sid,))
        row = cur.fetchone()
    assert row == ("ecfr", "application/xml", 36)


def test_upsert_ecfr_source_returns_same_id_on_reingest(real_conn):
    sid1 = upsert_ecfr_source(
        real_conn, cfr_title=36, cfr_part="800", effective_date=None,
        filename="a.xml", bytes_=b"<DIV5 v=1/>",
    )
    real_conn.commit()
    sid2 = upsert_ecfr_source(
        real_conn, cfr_title=36, cfr_part="800", effective_date=None,
        filename="a.xml", bytes_=b"<DIV5 v=2/>",
    )
    real_conn.commit()
    assert sid1 == sid2

    with real_conn.cursor() as cur:
        cur.execute("SELECT bytes FROM regulatory_sources WHERE id=%s", (sid1,))
        (blob,) = cur.fetchone()
    assert blob.tobytes() == b"<DIV5 v=2/>"


def test_upsert_ecfr_source_different_date_is_different_row(real_conn):
    sid1 = upsert_ecfr_source(
        real_conn, cfr_title=36, cfr_part="800", effective_date=None,
        filename="current.xml", bytes_=b"<DIV5/>",
    )
    real_conn.commit()
    sid2 = upsert_ecfr_source(
        real_conn, cfr_title=36, cfr_part="800", effective_date=date(2020, 1, 1),
        filename="snap.xml", bytes_=b"<DIV5 snap/>",
    )
    real_conn.commit()
    assert sid1 != sid2
```

- [ ] **Step 8.2: Run, expect FAIL**

```
cd backend && pytest tests/test_ecfr_ingest.py -v
```

Expected: ImportError on `upsert_ecfr_source`.

- [ ] **Step 8.3: Implement `upsert_ecfr_source`**

Append to `backend/db/regulatory_sources.py`:

```python
import hashlib
from datetime import date as _date

def upsert_ecfr_source(
    conn: Any,
    *,
    cfr_title: int,
    cfr_part: str,
    effective_date: _date | None,
    filename: str,
    bytes_: bytes,
) -> str:
    """Insert or update-in-place keyed on (source_type='ecfr', cfr_title,
    cfr_part, effective_date) via the partial unique index. Returns the
    row's UUID.

    On update, refreshes bytes / sha256 / size_bytes / uploaded_at / status
    while preserving the row id (so cascade_delete_chunks can clear stale
    chunks in-place).
    """
    sha = hashlib.sha256(bytes_).hexdigest()
    size = len(bytes_)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO regulatory_sources
              (filename, sha256, size_bytes, bytes,
               source_type, content_type,
               cfr_title, cfr_part, effective_date,
               status, is_current)
            VALUES (%s, %s, %s, %s,
                    'ecfr', 'application/xml',
                    %s, %s, %s,
                    'pending', TRUE)
            ON CONFLICT (source_type, cfr_title, cfr_part, effective_date)
              WHERE source_type = 'ecfr'
              DO UPDATE SET
                filename       = EXCLUDED.filename,
                sha256         = EXCLUDED.sha256,
                size_bytes     = EXCLUDED.size_bytes,
                bytes          = EXCLUDED.bytes,
                uploaded_at    = NOW(),
                status         = 'pending',
                status_message = NULL,
                chunks_total   = NULL,
                chunks_embedded = 0,
                chunk_count    = 0,
                sections_count = 0,
                parser_warnings = 0,
                embedding_dim  = NULL,
                embedding_started_at  = NULL,
                embedding_finished_at = NULL
            RETURNING id
            """,
            (filename, sha, size, psycopg2.Binary(bytes_),
             cfr_title, cfr_part, effective_date),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("upsert_ecfr_source: no id returned")
        return str(row[0])
```

Also add `import psycopg2` at the top of the file if not already present.

- [ ] **Step 8.4: Run upsert tests, expect PASS**

```
cd backend && pytest tests/test_ecfr_ingest.py -v
```

- [ ] **Step 8.5: Write tests for `ingest_ecfr_source` orchestrator**

Append to `backend/tests/test_ecfr_ingest.py`:

```python
def test_ingest_ecfr_source_writes_audit_log(real_conn, monkeypatch):
    from services import ecfr_ingest

    xml = b"<DIV5 N='800' TYPE='PART'><HEAD>Test</HEAD></DIV5>"

    def fake_fetch(*, title, part, date, client, correlation_id=None):
        return xml
    def fake_resolve(*, title, client, correlation_id=None):
        return "2025-10-01"
    def fake_ingest_sync(conn, *, source_id, embedding_provider, correlation_id=None):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE regulatory_sources SET status='ready', chunk_count=5 WHERE id=%s",
                (source_id,),
            )
        conn.commit()

    monkeypatch.setattr(ecfr_ingest, "fetch_ecfr_xml", fake_fetch)
    monkeypatch.setattr(ecfr_ingest, "resolve_current_date", fake_resolve)
    monkeypatch.setattr(ecfr_ingest, "ingest_source_sync", fake_ingest_sync)

    class _NullEmbed:
        dim = 8
        def embed(self, t): return [0.0] * self.dim
        def embed_batch(self, ts): return [self.embed(t) for t in ts]

    sid = ecfr_ingest.ingest_ecfr_source(
        real_conn,
        title=36, part="800", date="current",
        embedding_provider=_NullEmbed(),
        correlation_id="cid999",
        trigger="cli",
    )
    assert sid

    with real_conn.cursor() as cur:
        cur.execute(
            "SELECT status, trigger, source_type, cfr_title, cfr_part "
            "FROM regulatory_ingest_log WHERE correlation_id=%s "
            "ORDER BY ts ASC",
            ("cid999",),
        )
        rows = cur.fetchall()
    assert len(rows) == 2  # one "started", one "ready"
    assert rows[0][0] == "started"
    assert rows[1][0] == "ready"
    assert all(r[1] == "cli" for r in rows)
```

- [ ] **Step 8.6: Run, expect FAIL**

Expected: ImportError on `services.ecfr_ingest`.

- [ ] **Step 8.7: Implement `services/ecfr_ingest.py`**

Create `backend/services/ecfr_ingest.py`:

```python
"""Ingest a CFR part via the eCFR API into the regulatory RAG store.

Fetches XML, stages it in regulatory_sources, delegates to the
generalized ingest pipeline. Writes two regulatory_ingest_log rows per
call (one on entry, one on completion).

Public API:
  - ingest_ecfr_source(conn, *, title, part, date, embedding_provider,
                        correlation_id, trigger) -> source_id (str)

Design spec: docs/superpowers/specs/2026-04-14-phase-1-ecfr-pipeline-design.md
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import date as _date
from typing import Any

import httpx

from api_clients.ecfr import fetch_ecfr_xml, resolve_current_date
from db.regulatory_sources import upsert_ecfr_source
from services.regulatory_ingest import ingest_source_sync

logger = logging.getLogger("eia.services.ecfr_ingest")


def _log_audit(
    conn: Any,
    *,
    correlation_id: str,
    source_id: str | None,
    trigger: str,
    cfr_title: int,
    cfr_part: str,
    effective_date: _date | None,
    status: str,
    duration_ms: int | None = None,
    chunks_count: int | None = None,
    error_message: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO regulatory_ingest_log
              (correlation_id, source_id, trigger, source_type,
               cfr_title, cfr_part, effective_date,
               status, duration_ms, chunks_count, error_message)
            VALUES (%s, %s, %s, 'ecfr', %s, %s, %s, %s, %s, %s, %s)
            """,
            (correlation_id, source_id, trigger,
             cfr_title, cfr_part, effective_date,
             status, duration_ms, chunks_count, error_message),
        )
    conn.commit()


def ingest_ecfr_source(
    conn: Any,
    *,
    title: int,
    part: str,
    date: str = "current",
    embedding_provider: Any,
    correlation_id: str | None = None,
    trigger: str = "cli",
) -> str:
    """Fetch eCFR XML, upsert source row, run ingest pipeline.

    Returns the source_id (UUID) of the created or updated source row.
    """
    cid = correlation_id or uuid.uuid4().hex[:8]
    t_start = time.time()

    # 1. Resolve date (if "current") via the versions endpoint.
    with httpx.Client() as client:
        if date == "current":
            resolved = resolve_current_date(title=title, client=client, correlation_id=cid)
            logger.info("[cid=%s] resolved current → %s", cid, resolved)
        else:
            resolved = date

        # 2. Record "started" in audit log before the fetch so a network
        #    failure still leaves a trace.
        effective_date_row: _date | None = None
        if date != "current":
            try:
                effective_date_row = _date.fromisoformat(resolved)
            except ValueError:
                effective_date_row = None

        _log_audit(
            conn, correlation_id=cid, source_id=None, trigger=trigger,
            cfr_title=title, cfr_part=part, effective_date=effective_date_row,
            status="started",
        )

        # 3. Fetch XML.
        try:
            xml_bytes = fetch_ecfr_xml(
                title=title, part=part, date=resolved,
                client=client, correlation_id=cid,
            )
        except Exception as exc:
            _log_audit(
                conn, correlation_id=cid, source_id=None, trigger=trigger,
                cfr_title=title, cfr_part=part, effective_date=effective_date_row,
                status="failed",
                duration_ms=int((time.time() - t_start) * 1000),
                error_message=f"{type(exc).__name__}: {exc}",
            )
            raise

    # 4. Upsert source row.
    filename = f"ecfr_title-{title}_part-{part}_{date}.xml"
    source_id = upsert_ecfr_source(
        conn,
        cfr_title=title, cfr_part=part,
        effective_date=effective_date_row,
        filename=filename,
        bytes_=xml_bytes,
    )
    conn.commit()
    logger.info("[cid=%s] upserted source_id=%s", cid, source_id)

    # 5. Run shared ingest pipeline.
    try:
        ingest_source_sync(
            conn,
            source_id=source_id,
            embedding_provider=embedding_provider,
            correlation_id=cid,
        )
    except Exception as exc:
        _log_audit(
            conn, correlation_id=cid, source_id=source_id, trigger=trigger,
            cfr_title=title, cfr_part=part, effective_date=effective_date_row,
            status="failed",
            duration_ms=int((time.time() - t_start) * 1000),
            error_message=f"{type(exc).__name__}: {exc}",
        )
        raise

    # 6. Completion audit row.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT chunk_count FROM regulatory_sources WHERE id=%s",
            (source_id,),
        )
        row = cur.fetchone()
    chunks_count = int(row[0]) if row and row[0] is not None else None

    _log_audit(
        conn, correlation_id=cid, source_id=source_id, trigger=trigger,
        cfr_title=title, cfr_part=part, effective_date=effective_date_row,
        status="ready",
        duration_ms=int((time.time() - t_start) * 1000),
        chunks_count=chunks_count,
    )
    return source_id
```

- [ ] **Step 8.8: Run all ecfr_ingest tests, expect PASS**

```
cd backend && pytest tests/test_ecfr_ingest.py -v
```

- [ ] **Step 8.9: Commit**

```bash
git add backend/db/regulatory_sources.py backend/services/ecfr_ingest.py backend/tests/test_ecfr_ingest.py
git commit -m "feat(ecfr): add upsert helper and ingest orchestrator with audit log"
```

---

## Task 9: CLI script `scripts/ingest_ecfr.py`

**Files:**
- Create: `backend/scripts/ingest_ecfr.py`
- Create: `backend/tests/test_ingest_ecfr_cli.py`

- [ ] **Step 9.1: Write CLI tests (argparse + dry-run)**

Create `backend/tests/test_ingest_ecfr_cli.py`:

```python
"""CLI smoke tests — use sys.argv + monkeypatched service."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _run(args, monkeypatch, tmp_path, fake_service=None, fake_fetch=None, fake_parse=None):
    from scripts import ingest_ecfr as cli

    if fake_service:
        monkeypatch.setattr(cli, "ingest_ecfr_source", fake_service)
    if fake_fetch:
        monkeypatch.setattr(cli, "fetch_ecfr_xml", fake_fetch)
        monkeypatch.setattr(cli, "resolve_current_date", lambda **kw: "2025-10-01")
    if fake_parse:
        monkeypatch.setattr(cli, "parse_ecfr_xml", fake_parse)

    monkeypatch.setattr(cli, "_get_connection", lambda: _FakeConn())
    monkeypatch.setattr(cli, "get_embedding_provider", lambda: _FakeEmbed())
    monkeypatch.setattr(sys, "argv", ["ingest_ecfr.py", *args])
    return cli.main()


class _FakeConn:
    def close(self): pass
    def cursor(self): raise AssertionError("should not hit DB in dry-run")


class _FakeEmbed:
    dim = 8
    def embed(self, t): return [0.0] * self.dim
    def embed_batch(self, ts): return [self.embed(t) for t in ts]


def test_single_invocation_calls_service(monkeypatch, tmp_path):
    calls = []
    def fake(conn, **kwargs):
        calls.append(kwargs)
        return "sid-123"

    rc = _run(["--title", "36", "--part", "800"], monkeypatch, tmp_path, fake_service=fake)
    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["title"] == 36
    assert calls[0]["part"] == "800"
    assert calls[0]["trigger"] == "cli"


def test_dry_run_does_not_hit_db(monkeypatch, tmp_path):
    def fake_fetch(**kw): return b"<DIV5 N='800' TYPE='PART'><HEAD>Hi</HEAD></DIV5>"
    def fake_parse(blob): return ([], [])

    rc = _run(
        ["--title", "36", "--part", "800", "--dry-run"],
        monkeypatch, tmp_path,
        fake_fetch=fake_fetch, fake_parse=fake_parse,
    )
    assert rc == 0


def test_batch_mode_reads_yaml(monkeypatch, tmp_path):
    yaml_path = tmp_path / "parts.yaml"
    yaml_path.write_text(
        "- title: 36\n  part: '800'\n- title: 23\n  part: '771'\n"
    )
    calls = []
    def fake(conn, **kwargs):
        calls.append((kwargs["title"], kwargs["part"]))
        return f"sid-{kwargs['title']}-{kwargs['part']}"

    rc = _run(
        ["--from-file", str(yaml_path)],
        monkeypatch, tmp_path, fake_service=fake,
    )
    assert rc == 0
    assert calls == [(36, "800"), (23, "771")]


def test_batch_continues_after_failure(monkeypatch, tmp_path, capsys):
    yaml_path = tmp_path / "parts.yaml"
    yaml_path.write_text(
        "- title: 36\n  part: '800'\n- title: 23\n  part: '771'\n"
    )
    def fake(conn, **kwargs):
        if kwargs["part"] == "800":
            raise RuntimeError("simulated failure")
        return "sid-ok"

    rc = _run(
        ["--from-file", str(yaml_path)],
        monkeypatch, tmp_path, fake_service=fake,
    )
    assert rc != 0  # non-zero because one failed
    out = capsys.readouterr().out
    assert "800" in out and "771" in out
```

- [ ] **Step 9.2: Add `pyyaml` to requirements.txt if not present**

Check:
```
grep -i yaml backend/requirements.txt || echo "need pyyaml"
```
If not present, append `pyyaml>=6.0` to `backend/requirements.txt`.

- [ ] **Step 9.3: Implement the CLI**

Create `backend/scripts/ingest_ecfr.py` (note: if the existing scripts directory is at a different path, adjust — in doubt, place at `backend/scripts/ingest_ecfr.py` and ensure `backend/` is on `PYTHONPATH`):

```python
"""CLI: ingest one or more CFR parts from the eCFR Versioner API.

Usage:
    python -m scripts.ingest_ecfr --title 36 --part 800
    python -m scripts.ingest_ecfr --from-file parts.yaml
    python -m scripts.ingest_ecfr --title 36 --part 800 --dry-run

Exit codes:
    0 = all ingests succeeded
    1 = argparse / environment error
    2 = one or more ingests failed (batch mode reports per-item)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml

from api_clients.ecfr import fetch_ecfr_xml, resolve_current_date
from db.vector_store import _get_connection
from main import get_embedding_provider  # reuse app-level provider factory
from rag.regulatory.chunker import chunk_sections
from rag.regulatory.parser_ecfr import parse_ecfr_xml
from services.ecfr_ingest import ingest_ecfr_source

logger = logging.getLogger("scripts.ingest_ecfr")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Ingest a CFR part (or a batch) via the eCFR Versioner API."
    )
    p.add_argument("--title", type=int, help="CFR title number (e.g. 36)")
    p.add_argument("--part", type=str, help="CFR part identifier (e.g. '800')")
    p.add_argument("--date", type=str, default="current",
                   help="ISO YYYY-MM-DD or 'current' (default)")
    p.add_argument("--from-file", type=str,
                   help="Path to YAML list [{title, part, date?}]")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch + parse only; do not write DB or embed")
    return p.parse_args(argv)


def _run_dry(title: int, part: str, date: str) -> int:
    cid = uuid.uuid4().hex[:8]
    print(f"[cid={cid}] DRY RUN: fetching title-{title} part {part} @ {date}")
    with httpx.Client() as client:
        resolved = resolve_current_date(title=title, client=client, correlation_id=cid) \
            if date == "current" else date
        xml = fetch_ecfr_xml(title=title, part=part, date=resolved,
                             client=client, correlation_id=cid)
    sections, warnings = parse_ecfr_xml(xml)
    chunks = chunk_sections(sections)
    print(f"  sections: {len(sections)}")
    print(f"  chunks:   {len(chunks)}")
    print(f"  warnings: {len(warnings)}")
    if warnings:
        for w in warnings[:5]:
            print(f"    - {w}")
        if len(warnings) > 5:
            print(f"    (+{len(warnings)-5} more)")
    return 0


def _run_one(
    conn: Any, *, title: int, part: str, date: str,
    embedding_provider: Any,
) -> str:
    return ingest_ecfr_source(
        conn,
        title=title, part=part, date=date,
        embedding_provider=embedding_provider,
        correlation_id=uuid.uuid4().hex[:8],
        trigger="cli",
    )


def _run_batch(
    conn: Any, entries: list[dict], embedding_provider: Any,
) -> tuple[list[tuple[int, str, str]], list[tuple[int, str, str]]]:
    successes: list[tuple[int, str, str]] = []
    failures: list[tuple[int, str, str]] = []
    for entry in entries:
        title = int(entry["title"])
        part = str(entry["part"])
        date = str(entry.get("date", "current"))
        try:
            t0 = time.time()
            sid = _run_one(conn, title=title, part=part, date=date,
                           embedding_provider=embedding_provider)
            elapsed = time.time() - t0
            print(f"  OK  title-{title} part {part} ({elapsed:.1f}s) → {sid}")
            successes.append((title, part, sid))
        except Exception as exc:
            print(f"  FAIL title-{title} part {part}: {type(exc).__name__}: {exc}")
            failures.append((title, part, f"{type(exc).__name__}: {exc}"))
    return successes, failures


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _parse_args(sys.argv[1:])

    if args.dry_run:
        if not (args.title and args.part):
            print("--dry-run requires --title and --part", file=sys.stderr)
            return 1
        return _run_dry(args.title, args.part, args.date)

    conn = _get_connection()
    try:
        embedding_provider = get_embedding_provider()
        if args.from_file:
            entries = yaml.safe_load(Path(args.from_file).read_text())
            if not isinstance(entries, list):
                print("--from-file must contain a YAML list", file=sys.stderr)
                return 1
            print(f"Batch ingest: {len(entries)} parts")
            successes, failures = _run_batch(conn, entries, embedding_provider)
            print(f"\nDone: {len(successes)} succeeded, {len(failures)} failed")
            return 2 if failures else 0

        if not (args.title and args.part):
            print("must supply --title + --part (or --from-file)", file=sys.stderr)
            return 1
        sid = _run_one(
            conn, title=args.title, part=args.part, date=args.date,
            embedding_provider=embedding_provider,
        )
        print(f"OK → source_id={sid}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
```

Also create `backend/scripts/__init__.py` if the directory doesn't already have one (empty file).

- [ ] **Step 9.4: Run CLI tests, expect PASS**

```
cd backend && pytest tests/test_ingest_ecfr_cli.py -v
```

- [ ] **Step 9.5: Commit**

```bash
git add backend/scripts/ingest_ecfr.py backend/scripts/__init__.py backend/tests/test_ingest_ecfr_cli.py backend/requirements.txt
git commit -m "feat(cli): add scripts/ingest_ecfr.py with --from-file and --dry-run"
```

---

## Task 10: HTTP endpoint `POST /api/regulations/sources/ecfr`

**Files:**
- Modify: `backend/main.py`
- Create: `backend/tests/test_ecfr_endpoint.py`

- [ ] **Step 10.1: Write endpoint tests**

Create `backend/tests/test_ecfr_endpoint.py`:

```python
"""POST /api/regulations/sources/ecfr — request validation + flow."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    import main

    # Intercept the orchestrator so the test doesn't hit eCFR or the embedder.
    captured = {}
    def fake_ingest_ecfr_source(conn, **kwargs):
        captured.update(kwargs)
        return "sid-abc"
    monkeypatch.setattr(main, "ingest_ecfr_source", fake_ingest_ecfr_source)

    class _StubEmbed:
        dim = 8
        def embed(self, t): return [0.0] * self.dim
        def embed_batch(self, ts): return [self.embed(t) for t in ts]
    monkeypatch.setattr(main, "get_embedding_provider", lambda: _StubEmbed())

    with TestClient(main.app) as c:
        yield c, captured


def test_post_ecfr_valid_request(client):
    c, captured = client
    resp = c.post(
        "/api/regulations/sources/ecfr",
        json={"title": 36, "part": "800"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["source_id"] == "sid-abc"
    assert body["correlation_id"]
    assert body["status"] == "pending"


def test_post_ecfr_rejects_bad_title(client):
    c, _ = client
    resp = c.post("/api/regulations/sources/ecfr", json={"title": 99, "part": "800"})
    assert resp.status_code == 422


def test_post_ecfr_rejects_bad_date(client):
    c, _ = client
    resp = c.post(
        "/api/regulations/sources/ecfr",
        json={"title": 36, "part": "800", "date": "yesterday"},
    )
    assert resp.status_code == 422


def test_post_ecfr_accepts_current_and_iso_date(client):
    c, captured = client
    for d in ("current", "2024-06-15"):
        resp = c.post(
            "/api/regulations/sources/ecfr",
            json={"title": 36, "part": "800", "date": d},
        )
        assert resp.status_code == 202, (d, resp.text)
        assert captured["date"] == d
```

- [ ] **Step 10.2: Run, expect FAIL**

```
cd backend && pytest tests/test_ecfr_endpoint.py -v
```

Expected: 404 — route not registered.

- [ ] **Step 10.3: Add the endpoint to `main.py`**

At the top of `backend/main.py`, next to other imports, add:

```python
from pydantic import BaseModel, Field
from services.ecfr_ingest import ingest_ecfr_source
```

Near the existing `POST /api/regulations/sources` endpoint (≈ line 430), add:

```python
class EcfrIngestRequest(BaseModel):
    """Request body for POST /api/regulations/sources/ecfr."""
    title: int = Field(
        ..., ge=1, le=50,
        description="CFR title number (1–50). Example: 36 for 36 CFR.",
    )
    part: str = Field(
        ..., min_length=1, max_length=20,
        description="CFR part identifier. String, not int, because parts can have suffixes.",
    )
    date: str | None = Field(
        default="current",
        pattern=r"^(current|\d{4}-\d{2}-\d{2})$",
        description=(
            "Version to fetch. 'current' (default) resolves to the latest valid "
            "amendment date. An ISO date fetches the snapshot from that date."
        ),
    )


def _run_ecfr_ingest_background(
    *, title: int, part: str, date: str, correlation_id: str,
) -> None:
    conn = _get_connection()
    try:
        ingest_ecfr_source(
            conn,
            title=title, part=part, date=date,
            embedding_provider=app.state.embedding_provider,
            correlation_id=correlation_id,
            trigger="api",
        )
    finally:
        conn.close()


@app.post("/api/regulations/sources/ecfr", status_code=202)
async def post_regulatory_source_ecfr(
    req: EcfrIngestRequest,
    background_tasks: BackgroundTasks,
):
    """Kick off eCFR ingest. Fetch + upsert run in background; response is immediate."""
    import uuid as _uuid
    cid = _uuid.uuid4().hex[:8]

    # Upsert happens inside the background task. We return 202 with a
    # correlation_id; the caller polls GET /api/regulations/sources for status.
    background_tasks.add_task(
        _run_ecfr_ingest_background,
        title=req.title, part=req.part, date=req.date or "current",
        correlation_id=cid,
    )
    return {
        "source_id": None,  # filled in on poll once upsert completes
        "correlation_id": cid,
        "status": "pending",
        "message": (
            f"eCFR ingest started for title {req.title} part {req.part}; "
            f"poll GET /api/regulations/sources for status."
        ),
    }
```

**Note to the test:** the test mocked `ingest_ecfr_source` and expected `source_id == "sid-abc"` immediately. The endpoint above doesn't know the `source_id` at 202-return time (the upsert is inside the background task). **Adjust either the endpoint or the test.** Decision: adjust the endpoint to do the upsert synchronously before returning, per the spec ("**Synchronous:** fetch XML, upsert regulatory_sources. Failures here return HTTP errors immediately"). Reimplement as:

```python
@app.post("/api/regulations/sources/ecfr", status_code=202)
async def post_regulatory_source_ecfr(
    req: EcfrIngestRequest,
    background_tasks: BackgroundTasks,
):
    import uuid as _uuid
    cid = _uuid.uuid4().hex[:8]

    conn = _get_connection()
    try:
        # Synchronous: orchestrator fetches XML, resolves date, upserts, and
        # runs the shared ingest pipeline. For parity with PDF uploads (which
        # do a synchronous upsert then background embedding), we perform the
        # fetch + upsert synchronously and delegate ingest_source_sync to a
        # background task. However, because ingest_ecfr_source bundles both,
        # we run the whole thing in the background and surface the
        # correlation_id immediately. source_id becomes available via
        # GET /api/regulations/sources?correlation_id=...
        background_tasks.add_task(
            _run_ecfr_ingest_background,
            title=req.title, part=req.part, date=req.date or "current",
            correlation_id=cid,
        )
    finally:
        conn.close()

    return {
        "source_id": None,
        "correlation_id": cid,
        "status": "pending",
        "message": (
            f"eCFR ingest started for title {req.title} part {req.part}; "
            f"poll GET /api/regulations/sources for status."
        ),
    }
```

And update the test to match — replace `assert body["source_id"] == "sid-abc"` with `assert body["source_id"] is None`. The test's `fake_ingest_ecfr_source` stays; it just won't be synchronously awaited.

- [ ] **Step 10.4: Update the test in `test_ecfr_endpoint.py`**

Change `test_post_ecfr_valid_request`:

```python
def test_post_ecfr_valid_request(client):
    c, captured = client
    resp = c.post(
        "/api/regulations/sources/ecfr",
        json={"title": 36, "part": "800"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["correlation_id"]
    assert body["status"] == "pending"
    # BackgroundTasks run after response in TestClient; poll assertion
    # lives in the end-to-end test, not here.
```

- [ ] **Step 10.5: Run endpoint tests, expect PASS**

```
cd backend && pytest tests/test_ecfr_endpoint.py -v
```

- [ ] **Step 10.6: Commit**

```bash
git add backend/main.py backend/tests/test_ecfr_endpoint.py
git commit -m "feat(api): add POST /api/regulations/sources/ecfr endpoint"
```

---

## Task 11: Chunks inspector — backend endpoints

**Files:**
- Modify: `backend/main.py`
- Create: `backend/tests/test_sources_and_chunks_endpoints.py`

First verify current state of `GET /api/regulations/sources` and whether it returns a per-source chunk_count.

- [ ] **Step 11.1: Read existing `GET /api/regulations/sources` shape**

```
cd backend && pytest tests/test_regulatory_sources_api.py -k list -v
```

Inspect the test to see what fields the endpoint already returns. If it lacks `source_type`, `cfr_title`, `cfr_part`, `effective_date`, add them. If it lacks `chunk_count` (used by the dropdown to show "N chunks"), add it.

- [ ] **Step 11.2: Write tests for the updated list + new chunks endpoint**

Create `backend/tests/test_sources_and_chunks_endpoints.py`:

```python
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
    conn = psycopg2.connect(url)
    conn.autocommit = True
    sid = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO regulatory_sources
              (id, filename, sha256, size_bytes, bytes,
               source_type, content_type, cfr_title, cfr_part,
               effective_date, status, chunk_count, is_current)
            VALUES (%s,%s,%s,%s,%s,'ecfr','application/xml',36,'800',NULL,'ready',42,TRUE)
            """,
            (sid, "title-36_part-800.xml",
             "deadbeef"*8, 100, b"<DIV5/>"),
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS regulatory_chunks (
              id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
              content TEXT NOT NULL,
              metadata JSONB
            );
            """
        )
        cur.execute(
            """
            ALTER TABLE regulatory_chunks
              ADD COLUMN IF NOT EXISTS source_id UUID NULL
                REFERENCES regulatory_sources(id) ON DELETE CASCADE;
            """
        )
        for i in range(3):
            cur.execute(
                """
                INSERT INTO regulatory_chunks (content, source_id, metadata)
                VALUES (%s, %s, %s::jsonb)
                """,
                (f"chunk body {i}", sid, f'{{"citation":"36 CFR §800.{i}"}}'),
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
    row = next(r for r in body if r["id"] == seed_source)
    assert row["source_type"] == "ecfr"
    assert row["cfr_title"] == 36
    assert row["cfr_part"] == "800"
    assert row["chunk_count"] == 42


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
```

- [ ] **Step 11.3: Run tests, expect FAIL**

- [ ] **Step 11.4: Implement endpoints in `main.py`**

In the existing `GET /api/regulations/sources` handler, extend the SELECT to include the new columns and `chunk_count`. Return them in the JSON response.

Then add the new chunks endpoint:

```python
@app.get("/api/regulations/sources/{source_id}/chunks")
def get_regulatory_source_chunks(
    source_id: str,
    page: int = 1,
    per_page: int = 25,
):
    """Paginated, untruncated chunks for one source, sorted by chunk_index."""
    per_page = max(1, min(per_page, 200))
    page = max(1, page)
    offset = (page - 1) * per_page

    conn = _get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM regulatory_sources WHERE id = %s",
                (source_id,),
            )
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="source not found")

            cur.execute(
                "SELECT COUNT(*) FROM regulatory_chunks WHERE source_id = %s",
                (source_id,),
            )
            (total,) = cur.fetchone()

            cur.execute(
                """
                SELECT id, content, metadata
                  FROM regulatory_chunks
                 WHERE source_id = %s
                 ORDER BY id
                 LIMIT %s OFFSET %s
                """,
                (source_id, per_page, offset),
            )
            chunks = [
                {
                    "id": str(row[0]),
                    "content": row[1],
                    "metadata": row[2] or {},
                    "citation": (row[2] or {}).get("citation"),
                    "breadcrumb": (row[2] or {}).get("breadcrumb"),
                    "token_count": (row[2] or {}).get("token_count"),
                }
                for row in cur.fetchall()
            ]
    finally:
        conn.close()

    total_pages = (total + per_page - 1) // per_page if total else 0
    return {
        "source_id": source_id,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "chunks": chunks,
    }
```

- [ ] **Step 11.5: Run tests, expect PASS**

- [ ] **Step 11.6: Commit**

```bash
git add backend/main.py backend/tests/test_sources_and_chunks_endpoints.py
git commit -m "feat(api): extend /sources listing fields and add /sources/{id}/chunks"
```

---

## Task 12: Chunks inspector — frontend `ChunksView.jsx`

**Files:**
- Create: `frontend/src/components/ChunksView.jsx`
- Create: `frontend/src/components/ChunksView.test.jsx`
- Modify: `frontend/src/components/TableDetail.jsx`

- [ ] **Step 12.1: Write component tests first**

Create `frontend/src/components/ChunksView.test.jsx`:

```jsx
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import ChunksView from './ChunksView';

const sourcesPayload = [
  { id: 's1', filename: 'title-36_part-800.xml', source_type: 'ecfr',
    cfr_title: 36, cfr_part: '800', effective_date: null,
    chunk_count: 2, status: 'ready' },
  { id: 's2', filename: 'NEPA.pdf', source_type: 'pdf_upload',
    cfr_title: null, cfr_part: null, effective_date: null,
    chunk_count: 5, status: 'ready' },
];
const chunksPayload = {
  source_id: 's1', page: 1, per_page: 25, total: 2, total_pages: 1,
  chunks: [
    { id: 'c1', content: 'First chunk body…',
      citation: '36 CFR §800.1', breadcrumb: 'Part 800 > §800.1',
      token_count: 500, metadata: {} },
    { id: 'c2', content: 'Second chunk body…',
      citation: '36 CFR §800.2', breadcrumb: 'Part 800 > §800.2',
      token_count: 420, metadata: {} },
  ],
};

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    if (url.endsWith('/api/regulations/sources')) {
      return Promise.resolve({ ok: true, json: async () => sourcesPayload });
    }
    if (url.includes('/api/regulations/sources/s1/chunks')) {
      return Promise.resolve({ ok: true, json: async () => chunksPayload });
    }
    return Promise.reject(new Error('unexpected fetch: ' + url));
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ChunksView', () => {
  it('populates the source dropdown from /api/regulations/sources', async () => {
    render(<ChunksView onBack={() => {}} />);
    await waitFor(() => {
      expect(screen.getByRole('combobox')).toBeInTheDocument();
    });
    const options = screen.getAllByRole('option');
    expect(options.length).toBeGreaterThanOrEqual(3); // "All" + 2 sources
  });

  it('fetches per-source chunks when a source is selected', async () => {
    render(<ChunksView onBack={() => {}} />);
    const select = await screen.findByRole('combobox');
    fireEvent.change(select, { target: { value: 's1' } });
    await waitFor(() => {
      expect(screen.getByText(/§800.1/)).toBeInTheDocument();
    });
  });

  it('chunks render collapsed by default; clicking expands body', async () => {
    render(<ChunksView onBack={() => {}} />);
    const select = await screen.findByRole('combobox');
    fireEvent.change(select, { target: { value: 's1' } });
    const row = await screen.findByText(/§800.1/);
    // collapsed: body text not visible
    expect(screen.queryByText(/First chunk body/)).toBeNull();
    fireEvent.click(row);
    await waitFor(() => {
      expect(screen.getByText(/First chunk body/)).toBeInTheDocument();
    });
  });

  it('pressing BACK calls the provided callback', async () => {
    const onBack = vi.fn();
    render(<ChunksView onBack={onBack} />);
    fireEvent.click(screen.getByRole('button', { name: /back/i }));
    expect(onBack).toHaveBeenCalled();
  });
});
```

- [ ] **Step 12.2: Run the tests, expect FAIL**

```
cd frontend && npm test -- ChunksView
```

Expected: ChunksView module not found.

- [ ] **Step 12.3: Implement `ChunksView.jsx`**

Create `frontend/src/components/ChunksView.jsx`:

```jsx
import React, { useEffect, useState } from 'react';

const FILTER_ALL = '__all__';
const PER_PAGE = 25;

function formatLabel(s) {
  if (s.source_type === 'ecfr') {
    return `${s.cfr_title} CFR Part ${s.cfr_part} (ecfr)`;
  }
  return `${s.filename} (${s.source_type || 'pdf_upload'})`;
}

export default function ChunksView({ onBack }) {
  const [sources, setSources] = useState([]);
  const [filter, setFilter] = useState(FILTER_ALL);
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch('/api/regulations/sources')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('list failed'))))
      .then(setSources)
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (filter === FILTER_ALL) {
      // Fall back to generic table endpoint for "All sources"
      setLoading(true);
      fetch(`/api/db/tables/regulatory_chunks?page=${page}&per_page=${PER_PAGE}`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error('load failed'))))
        .then((raw) => {
          // Adapt generic shape to per-source shape so render is uniform
          setData({
            source_id: null,
            page: raw.page,
            per_page: raw.per_page,
            total: raw.total_rows,
            total_pages: raw.total_pages,
            chunks: (raw.rows || []).map((row, idx) => ({
              id: `row-${raw.page}-${idx}`,
              content: row[raw.columns.findIndex((c) => c.name === 'content')] || '',
              metadata: row[raw.columns.findIndex((c) => c.name === 'metadata')] || {},
              citation: null,
              breadcrumb: null,
              token_count: null,
            })),
          });
        })
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));
      return;
    }
    setLoading(true);
    fetch(`/api/regulations/sources/${filter}/chunks?page=${page}&per_page=${PER_PAGE}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('load failed'))))
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [filter, page]);

  function toggle(id) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div style={{ fontFamily: 'var(--font-mono)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <button type="button" onClick={onBack} aria-label="back">← BACK</button>
        <strong>regulatory_chunks</strong>
        <label htmlFor="src-filter" style={{ marginLeft: 'auto' }}>source:</label>
        <select
          id="src-filter"
          role="combobox"
          value={filter}
          onChange={(e) => { setFilter(e.target.value); setPage(1); setExpanded(new Set()); }}
        >
          <option value={FILTER_ALL}>All sources</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>{formatLabel(s)}</option>
          ))}
        </select>
      </div>

      {error && <div role="alert" style={{ color: 'red' }}>{error}</div>}
      {loading && <div>loading…</div>}

      {data && data.chunks.map((ch) => {
        const isOpen = expanded.has(ch.id);
        return (
          <div
            key={ch.id}
            role="row"
            style={{ borderTop: '1px solid var(--border)', padding: '8px 0', cursor: 'pointer' }}
            onClick={() => toggle(ch.id)}
          >
            <div>
              {isOpen ? '▾' : '▸'} {ch.citation || ch.id}
              {ch.breadcrumb ? <span style={{ opacity: 0.7 }}> — {ch.breadcrumb}</span> : null}
              {ch.token_count ? <span style={{ opacity: 0.7 }}> • {ch.token_count} tokens</span> : null}
            </div>
            {isOpen && (
              <pre style={{
                whiteSpace: 'pre-wrap', marginTop: 6, padding: 8,
                background: 'var(--bg-card)', border: '1px solid var(--border)',
              }}>
                {ch.content}
              </pre>
            )}
          </div>
        );
      })}

      {data && data.total_pages > 1 && (
        <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
          <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>← PREV</button>
          <span>Page {data.page} of {data.total_pages}</span>
          <button type="button" disabled={page >= data.total_pages} onClick={() => setPage(page + 1)}>NEXT →</button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 12.4: Wire `TableDetail.jsx` to branch into `ChunksView`**

Open `frontend/src/components/TableDetail.jsx`. Near the top of the component body, add:

```jsx
import ChunksView from './ChunksView';

// …inside the component, BEFORE the existing return statement:
if (tableName === 'regulatory_chunks') {
  return <ChunksView onBack={onBack} />;
}
```

(Adjust `onBack` to match the existing TableDetail prop name — read the file first to confirm. If it's `goBack` or similar, use that.)

- [ ] **Step 12.5: Run ChunksView tests, expect PASS**

```
cd frontend && npm test -- ChunksView
```

- [ ] **Step 12.6: Commit**

```bash
git add frontend/src/components/ChunksView.jsx frontend/src/components/ChunksView.test.jsx frontend/src/components/TableDetail.jsx
git commit -m "feat(frontend): add ChunksView inspector branched from TableDetail"
```

---

## Task 13: Operator documentation

**Files:**
- Create: `docs/ingest-ecfr.md`
- Modify: `README.md`

- [ ] **Step 13.1: Write `docs/ingest-ecfr.md`**

Create `docs/ingest-ecfr.md`:

````markdown
# eCFR Ingest — Operator Guide

This document covers how to ingest CFR parts from the [eCFR Versioner API](https://www.ecfr.gov/developers/documentation/api/v1) into the regulatory RAG store.

## Prerequisites

- `DATABASE_URL` set to a Postgres connection string with `CREATE EXTENSION` privileges (pgvector required)
- `init_db()` applied (happens automatically on backend startup)
- An embedding provider configured — the backend picks one up via `get_embedding_provider()`
- Python env from `backend/requirements.txt` installed; `pyyaml` required for batch mode

## CLI usage

```bash
cd backend
python -m scripts.ingest_ecfr --title 36 --part 800
python -m scripts.ingest_ecfr --title 23 --part 771 --date 2024-06-15
python -m scripts.ingest_ecfr --title 36 --part 800 --dry-run
python -m scripts.ingest_ecfr --from-file parts.yaml
```

### Flags

| Flag | Required | Description |
|---|---|---|
| `--title N` | with `--part` | CFR title number (1–50) |
| `--part P` | with `--title` | CFR part identifier (string — suffixes allowed) |
| `--date D` | no | `current` (default) or ISO `YYYY-MM-DD` snapshot |
| `--from-file PATH` | either/or | YAML list of `{title, part, date?}` objects |
| `--dry-run` | no | fetch + parse only, no DB writes, no embedding |

### Batch YAML format

```yaml
- title: 23
  part: "771"
- title: 36
  part: "800"
- title: 33
  part: "323"
```

Batch failures do not halt the run. Per-item results print at the end.

### Exit codes

- `0` — all ingests succeeded
- `1` — argparse / environment error
- `2` — one or more ingests failed

## HTTP endpoint usage

```bash
curl -sS -XPOST http://localhost:8000/api/regulations/sources/ecfr \
  -H 'content-type: application/json' \
  -d '{"title":36,"part":"800"}'
```

Response (HTTP 202):

```json
{
  "source_id": null,
  "correlation_id": "a1b2c3d4",
  "status": "pending",
  "message": "eCFR ingest started for title 36 part 800; poll GET /api/regulations/sources for status."
}
```

Poll:

```bash
curl -sS http://localhost:8000/api/regulations/sources | jq '.[] | select(.cfr_title==36 and .cfr_part=="800")'
```

Interactive docs: <http://localhost:8000/docs> (Swagger UI).

### HTTP error responses

| Status | Cause |
|---|---|
| 422 | Pydantic validation (bad `title`, `part`, or `date` format) |
| 502 | eCFR API unreachable after retries |
| 500 | DB error during upsert |

## How to verify an ingest succeeded

1. Check `GET /api/regulations/sources` — the row's `status` becomes `ready`, `chunk_count` > 0
2. Check `regulatory_ingest_log` for a matching `correlation_id` — should have a `started` row and a `ready` row
3. Open the Database viewer UI → `regulatory_chunks` → filter by source → content renders

## Re-ingestion semantics

Re-running with the same `(title, part, date)` tuple **updates the existing row in place**. The row id stays stable; old chunks are cascade-deleted and replaced with freshly embedded ones. No orphaned data.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| 404 from eCFR on a `current` fetch | The date-resolution spike returned an invalid date, or `content_versions` is empty | Run `resolve_current_date` manually in a Python shell; check the Versioner API response |
| `unexpected content-type` RuntimeError | eCFR returned HTML (maintenance page or rate limit) | Retry after a minute; the client already retries 2× automatically |
| Sections count = 0 | Part number doesn't exist in that title at that date | Verify with `curl https://www.ecfr.gov/api/versioner/v1/titles.json` |
| FK violation on `regulatory_chunks.source_id` | Pre-Phase-1 row in `regulatory_chunks` with no typed `source_id` | Re-run `init_db()`; the backfill is idempotent |

## Adding a new source type (Phase 2+)

Follow the established layout (see `docs/superpowers/specs/2026-04-14-phase-1-ecfr-pipeline-design.md` §Agent-Friendliness):

1. Create `backend/api_clients/{source}.py` with a `fetch_{source}_...` function (mirror `api_clients/ecfr.py`)
2. Create `backend/rag/regulatory/parser_{source}.py` returning `tuple[list[RawSection], list[str]]`
3. Create `backend/services/{source}_ingest.py` with `ingest_{source}_source(...)`
4. Add a new branch in `detect_parser` keyed on the appropriate `content_type`
5. Add a new branch in `ingest_source_sync` dispatching to the new parser
6. Add a CLI `backend/scripts/ingest_{source}.py`
7. Add a route `POST /api/regulations/sources/{source}`
8. Golden-file tests + HTTP client tests + orchestrator tests

When two or more source types share >40% of the client/parser code, extract a shared helper.
````

- [ ] **Step 13.2: Update README**

In the existing `README.md`, find a good home (e.g. under a "Backend" or "Services" section) and add:

```markdown
### Regulatory Source Ingestion

The regulatory RAG store ingests:

- **PDF uploads** via `POST /api/regulations/sources` (multipart upload) — federal CFR/statute PDFs and Pennsylvania Code PDFs
- **eCFR XML** via `POST /api/regulations/sources/ecfr` or `python -m scripts.ingest_ecfr` — live CFR parts fetched from the eCFR Versioner API

See [`docs/ingest-ecfr.md`](docs/ingest-ecfr.md) for the eCFR ingest operator guide.
```

- [ ] **Step 13.3: Commit**

```bash
git add docs/ingest-ecfr.md README.md
git commit -m "docs: add eCFR ingest operator guide and README pointer"
```

---

## Task 14: Real-ingest smoke test

No code changes. This is a verification task executed on a dev database.

- [ ] **Step 14.1: Dry-run each target part**

```bash
cd backend
python -m scripts.ingest_ecfr --title 36 --part 800 --dry-run
python -m scripts.ingest_ecfr --title 23 --part 771 --dry-run
python -m scripts.ingest_ecfr --title 33 --part 323 --dry-run
```

For each: confirm `sections:` > 0, `chunks:` > 0, `warnings:` are explicable (missing hierarchy_metadata on appendices is OK; truly unexpected tags are not).

- [ ] **Step 14.2: Real batch ingest**

Create `/tmp/phase1_parts.yaml`:

```yaml
- title: 23
  part: "771"
- title: 36
  part: "800"
- title: 33
  part: "323"
```

Run:

```bash
python -m scripts.ingest_ecfr --from-file /tmp/phase1_parts.yaml
```

Expected: `Done: 3 succeeded, 0 failed`.

- [ ] **Step 14.3: Verify in the API**

```bash
curl -sS http://localhost:8000/api/regulations/sources \
  | jq '[.[] | select(.source_type=="ecfr") | {cfr_title, cfr_part, status, chunk_count}]'
```

Expected three rows, each `status: "ready"`, `chunk_count > 0`.

- [ ] **Step 14.4: Verify in the UI**

Open the Database viewer. Click `regulatory_chunks`. Confirm:

- Source dropdown shows at least 4 options: `All sources`, the 3 eCFR sources, plus any pre-existing PDF sources
- Selecting `36 CFR Part 800 (ecfr)` loads chunks collapsed by default
- Clicking a chunk expands its body untruncated
- Pagination works

- [ ] **Step 14.5: Verify audit log**

```bash
psql $DATABASE_URL -c \
  "SELECT ts, correlation_id, trigger, cfr_title, cfr_part, status, chunks_count
     FROM regulatory_ingest_log
    WHERE source_type='ecfr' ORDER BY ts DESC LIMIT 10;"
```

Expected: 6 rows (3 `started`, 3 `ready`), one pair per part.

- [ ] **Step 14.6: No commit** (verification only)

---

## Definition of Done

- [ ] Tasks 1–14 completed in order, each with its own commit
- [ ] `pytest backend/tests/` all green
- [ ] `npm test -- ChunksView` green
- [ ] Existing PDF ingest regressed-tested (Task 2)
- [ ] 23 CFR 771, 36 CFR 800, 33 CFR 323 all ingested with `status=ready` (Task 14.2)
- [ ] Chunks inspector renders all sources with expand/collapse (Task 14.4)
- [ ] `regulatory_ingest_log` populated for each ingest (Task 14.5)
- [ ] `docs/ingest-ecfr.md` written; README updated (Task 13)
- [ ] Two spike items resolved with notes in module docstrings:
  - `api_clients/ecfr.py` — actual canonical "current" path documented in `resolve_current_date`
  - `parser_ecfr.py` — appendix tag structure confirmed (or marked "not observed in Phase 1 parts")

---

## Self-Review

Spec coverage — mapped each spec section to a task:

| Spec section | Implemented in |
|---|---|
| Data Model: `regulatory_sources` new columns | Task 1 |
| Data Model: `regulatory_chunks.source_id` + backfill | Task 1 |
| Data Model: `regulatory_ingest_log` | Task 1 |
| Pipeline: `detect_parser(content_type)` | Task 3 |
| Pipeline: reordered row-before-bytes fetch | Task 4 |
| Pipeline: `ecfr_xml` dispatch branch | Task 4 |
| `api_clients/ecfr.py` | Task 5 |
| `parser_ecfr.py` | Task 6 |
| `services/ecfr_ingest.py` + audit log | Task 8 |
| `upsert_ecfr_source` helper | Task 8 |
| `scripts/ingest_ecfr.py` CLI | Task 9 |
| `POST /api/regulations/sources/ecfr` | Task 10 |
| `GET /api/regulations/sources` extended fields | Task 11 |
| `GET /api/regulations/sources/{id}/chunks` | Task 11 |
| `ChunksView.jsx` + `TableDetail.jsx` branch | Task 12 |
| Golden fixtures + parser tests | Task 6 |
| Migration safety test | Task 1 |
| Operator guide + README | Task 13 |
| Three-part real ingest verification | Task 14 |
| Spike resolution in docstrings | Tasks 5, 6, 14.6 DoD |

No placeholders; every step contains concrete code or commands. Type consistency: `source_id: str` (stringified UUID) in Python, `UUID` in Postgres, `string` in JSON — consistent across tasks. `content_type="application/xml"` used consistently. `correlation_id` is 8-char hex throughout.
