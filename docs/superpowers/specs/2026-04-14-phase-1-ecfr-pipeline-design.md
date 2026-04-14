# Phase 1 — eCFR Ingest + Pipeline Generalization — Design Spec

**Date:** 2026-04-14
**Status:** Approved (pending spec review)
**Phase context:** First of three sequenced phases for expanding regulatory source coverage. Phase 2 = Federal Register JSON API. Phase 3 = state agency PDFs + second chunking strategy. Each phase has its own spec and implementation plan.

## Problem

The regulatory RAG pipeline ingests documents via a single PDF-only path. `services/regulatory_ingest.py:48` calls `pymupdf.open(..., filetype="pdf")` before any dispatch, making new document formats impossible without surgery. Two immediate needs:

1. Expand coverage to federal CFR parts beyond 40 CFR 1500–1508 (currently ingested as a single PDF). Target parts for Phase 1: 23 CFR 771 (FHWA NEPA), 36 CFR 800 (Section 106), 33 CFR 323 (CWA 404).
2. Use eCFR's structured XML API (`/api/versioner/v1/...`) rather than PDFs. XML provides unambiguous section boundaries, machine-readable citations via `hierarchy_metadata`, and automatic updates on re-ingest.

The pipeline must generalize to support multiple document formats (XML now, JSON in Phase 2) without duplicating orchestration, progress tracking, embedding fan-out, cascade-delete, or error-handling logic.

## Decisions

- **One generalized ingest pipeline**, not three. Only parser selection varies by `content_type`; everything else stays shared.
- **Inline `if/elif` dispatch** on `content_type` in `detect_parser`, not a parser registry. Promote to registry when format count justifies it (Group 3 or later).
- **Two trigger surfaces** — CLI script + HTTP endpoint — both on top of one service function.
- **Schema supports dated ingestion** (`effective_date` column) **but Phase 1 code only writes `current`**. Dated retrieval is a Phase-1.5 flip.
- **Re-ingest replaces in place** keyed on `(source_type, cfr_title, cfr_part, effective_date)` via existing `cascade_delete_chunks` → `upsert_chunks` pattern.
- **Phase 1 does not touch the existing 40 CFR 1500–1508 PDF ingest.** Validates the eCFR pipeline on three net-new parts. PDF→eCFR migration for 1500–1508 is a separate follow-up.
- **Chunks inspector UI is in scope** for Phase 1. Without it, Phase 1's output can't be meaningfully inspected (the generic DB viewer truncates cells at 100 characters; chunk content is thousands of characters).
- **Source provenance tracked on every chunk via typed `source_id UUID FK` column.** Existing JSONB `metadata.source_id` is preserved for backward compatibility.
- **Ingest audit log table** (`regulatory_ingest_log`) included in Phase 1 for auditability. Read-only audit history endpoint deferred to Phase 1.5.

## Scope — in and out

**In scope**
- Schema migration adding `source_type`, `content_type`, `effective_date`, `cfr_title`, `cfr_part` to `regulatory_sources`; adding typed `source_id` FK to `regulatory_chunks`; creating `regulatory_ingest_log`
- Generalize `detect_parser` to dispatch on `content_type`
- eCFR HTTP client, XML parser, ingest service function
- CLI `scripts/ingest_ecfr.py` (with `--from-file` batch mode, `--dry-run`)
- HTTP endpoint `POST /api/sources/ecfr`
- Chunks inspector: `/api/sources` listing endpoint, `/api/sources/{id}/chunks` detail endpoint, `ChunksView.jsx` component
- Ingest of 23 CFR 771, 36 CFR 800, 33 CFR 323 (net-new content)
- Tests: parser unit, HTTP client, service function, pipeline integration, frontend component, migration safety
- Operator guide `docs/ingest-ecfr.md`; README update; module/function docstrings; Pydantic field descriptions

**Out of scope (deferred)**
- Dated/historical ingestion (schema ready, code write path deferred)
- Re-ingesting 40 CFR 1500–1508 via eCFR (migration off the existing PDF source)
- Federal Register JSON API client (Phase 2)
- State-agency PDF parser + second chunking strategy (Phase 3)
- Audit history endpoint (`GET /api/sources/{id}/ingest-history`)
- Admin React form for the eCFR endpoint (Swagger UI + CLI cover Phase 1)
- Parser registry refactor (deferred until format count forces it)
- Shared HTTP retry helper (defer to Phase 2 when two API clients exist to generalize from)
- Scheduled/cron re-ingestion

## Known unknowns (implementation spikes)

Two items require short verification tasks during implementation, not design-time decisions:

1. **Canonical "current" URL format.** The naive `GET /api/versioner/v1/full/current/title-{N}.xml?part={P}` returned 404 in verification. Dated endpoint `GET /api/versioner/v1/full/{ISO-DATE}/title-{N}.xml?part={P}` works. Likely workflow: call `GET /api/versioner/v1/versions/title-{N}` to retrieve the latest valid amendment date, then fetch via the dated endpoint with that date. `ingest_ecfr_source(date="current", ...)` resolves internally. **Spike:** during implementation of `api_clients/ecfr.py`, verify the latest-valid-date workflow and document the actual "current" code path.
2. **Appendix tag structure.** 36 CFR 800 has no appendices. 23 CFR 771 verification was inconclusive (response appeared truncated). Presumed structure: `<DIV9 N="A" TYPE="APPENDIX">`. **Spike:** during parser implementation, fetch a part with confirmed appendices (e.g., 40 CFR 1508 if/when backfilled) and confirm. Parser logs a warning and skips any unexpected hierarchy element so unverified structures don't silently corrupt output.

## Data Model

Two tables modified, one new table. All migrations are additive — existing PDF ingest paths continue working with default values.

### `regulatory_sources` — new columns

```sql
ALTER TABLE regulatory_sources
  ADD COLUMN source_type    TEXT NOT NULL DEFAULT 'pdf_upload',
  ADD COLUMN content_type   TEXT NOT NULL DEFAULT 'application/pdf',
  ADD COLUMN effective_date DATE NULL,
  ADD COLUMN cfr_title      INT  NULL,
  ADD COLUMN cfr_part       TEXT NULL;

-- Partial unique index: only eCFR (and, later, other API sources) use the
-- tuple identity. PDF upload rows continue using SHA256 dedup.
CREATE UNIQUE INDEX regulatory_sources_identity_idx
  ON regulatory_sources (source_type, cfr_title, cfr_part, effective_date)
  WHERE source_type = 'ecfr';
```

- `source_type` distinguishes `pdf_upload` from `ecfr` (and later `federal_register`, etc.)
- `content_type` drives parser dispatch in `ingest_source_sync`
- `effective_date NULL` = "current/live version." A non-null date = snapshot at that date. Postgres's partial unique index correctly allows exactly one NULL-date row per `(source_type, cfr_title, cfr_part)` tuple.
- `cfr_title` / `cfr_part` nullable because PDF uploads don't have them.

### `regulatory_chunks` — promote `source_id` to typed column

```sql
-- Step 1: add nullable typed column + FK with cascade
ALTER TABLE regulatory_chunks
  ADD COLUMN source_id UUID NULL
    REFERENCES regulatory_sources(id) ON DELETE CASCADE;

-- Step 2: one-time backfill from existing metadata JSONB
UPDATE regulatory_chunks
   SET source_id = (metadata->>'source_id')::uuid
 WHERE source_id IS NULL
   AND metadata ? 'source_id';

-- Step 3: index for filter queries
CREATE INDEX regulatory_chunks_source_id_idx ON regulatory_chunks (source_id);

-- Step 4 (separate follow-up migration, after verifying zero nulls):
ALTER TABLE regulatory_chunks ALTER COLUMN source_id SET NOT NULL;
```

- Step 4 is deferred to a follow-up migration as a safety checkpoint. If step 2 missed rows (unexpected metadata shape), we notice before locking the schema.
- `ON DELETE CASCADE` means deleting a `regulatory_sources` row removes its chunks automatically.
- Existing `metadata.source_id` JSONB field retained for backward compatibility. New code prefers the typed column; a docstring on `source_id` states this preference.

### `regulatory_ingest_log` — new table for audit trail

```sql
CREATE TABLE regulatory_ingest_log (
  id             BIGSERIAL PRIMARY KEY,
  ts             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  correlation_id TEXT NOT NULL,
  source_id      UUID NULL REFERENCES regulatory_sources(id) ON DELETE SET NULL,
  trigger        TEXT NOT NULL,   -- 'cli' | 'api'
  source_type    TEXT NOT NULL,
  cfr_title      INT NULL,
  cfr_part       TEXT NULL,
  effective_date DATE NULL,
  status         TEXT NOT NULL,   -- 'started' | 'ready' | 'failed'
  duration_ms    INT NULL,
  chunks_count   INT NULL,
  error_message  TEXT NULL
);

CREATE INDEX regulatory_ingest_log_ts_idx ON regulatory_ingest_log (ts DESC);
CREATE INDEX regulatory_ingest_log_source_idx ON regulatory_ingest_log (source_id);
```

One row per ingest attempt. Start row written on entry, updated on completion. Enables queries like "show all failed ingests in the last 24h" and "how many times has 36 CFR 800 been re-ingested." Small volume (one row per admin action), high audit value.

## Backend — Pipeline Generalization

### `services/regulatory_ingest.py`

Current `detect_parser(blob)` and `ingest_source_sync` hardcode PDF. Changes:

```python
def detect_parser(blob: bytes, *, content_type: str) -> str:
    """Route bytes to the right parser based on content_type.

    EXTENSION POINT: add new content_type branches here.
    Pattern: see parser_ecfr.py for the eCFR XML reference implementation.
    See docs/ingest-ecfr.md 'Adding a new source type' for full procedure.
    """
    if content_type == "application/xml":
        return "ecfr_xml"
    if content_type == "application/pdf":
        # Existing PDF sniffing — unchanged
        doc = pymupdf.open(stream=blob, filetype="pdf")
        first_page_text = doc[0].get_text("text") if len(doc) > 0 else ""
        doc.close()
        if "Pennsylvania Code" in first_page_text:
            return "pa_code"
        return "federal"
    raise ValueError(f"unsupported content_type: {content_type!r}")


def ingest_source_sync(conn, *, source_id, embedding_provider, correlation_id=None):
    # ...existing status updates...
    row = get_source_by_id(conn, source_id)   # reordered: row before bytes
    if row is None:
        raise RuntimeError(f"source row not found: {source_id}")
    content_type = row["content_type"]
    blob = get_source_bytes(conn, source_id)
    # ...existing error path...

    parser_type = detect_parser(blob, content_type=content_type)
    if parser_type == "ecfr_xml":
        sections, warnings = parse_ecfr_xml(blob)
    elif parser_type == "pa_code":
        sections, warnings = parse_pa_code_pdf(blob)
    else:  # "federal" PDF
        sections, warnings = parse_pdf(blob)

    # ...rest unchanged: chunking, embedding, upsert, status, error handling...
```

Everything after parser selection (chunking, embedding, upsert, status updates, throttled progress callback, cascade-delete-then-upsert, error rollback) is unchanged.

## Backend — New Modules

### `backend/api_clients/ecfr.py`

HTTP client. Placement rationale: it's an HTTP client to an external API, which is what `api_clients/` is for. "Used at ingest time vs query time" is orthogonal.

```python
"""eCFR Versioner API v1 HTTP client.

Fetches CFR title/part XML from ecfr.gov. Ingest-time client (not used
by agents at query time — unlike other api_clients/*.py modules).

Public API:
  - fetch_ecfr_xml(title, part, date, client): bytes

Depends on: httpx (stdlib otherwise)
Used by: services/ecfr_ingest.py

Design spec: docs/superpowers/specs/2026-04-14-phase-1-ecfr-pipeline-design.md
"""
import httpx
import logging

logger = logging.getLogger("eia.api_clients.ecfr")

_ECFR_BASE_URL = "https://www.ecfr.gov/api/versioner/v1"
_MAX_RETRIES = 2
_RETRY_DELAY_S = 1.5


def fetch_ecfr_xml(
    *,
    title: int,
    part: str,
    date: str,              # ISO YYYY-MM-DD — caller resolves "current" → latest valid date
    client: httpx.Client,
    correlation_id: str | None = None,
) -> bytes:
    """Fetch one CFR part as XML. Returns raw bytes.

    Raises:
        httpx.HTTPStatusError: on 4xx/5xx after retries exhausted
        RuntimeError: on non-XML response
    """
    # Implementation mirrors api_clients/fema.py retry pattern.


def resolve_current_date(*, title: int, client: httpx.Client) -> str:
    """Return the latest valid amendment date for a CFR title.

    Spike at implementation time: confirm endpoint and response shape.
    Hypothesized: GET /api/versioner/v1/versions/title-{N} returns a list
    of valid dates; take the most recent. Document actual format here.
    """
```

~80–100 lines. Retry loop matches existing `api_clients/fema.py` pattern. No shared retry helper yet — that extraction comes in Phase 2 when there are two clients to generalize from.

### `backend/rag/regulatory/parser_ecfr.py`

XML → `list[RawSection]`. Mirrors `parser_pa_code.py` in shape. Uses stdlib `xml.etree.ElementTree` — no new dependency.

```python
"""eCFR XML → ordered list of RawSection records.

Parses the XML returned by the eCFR Versioner API. The response is a
single <DIV5 TYPE="PART"> element as root (no wrapping envelope).

Public API:
  - parse_ecfr_xml(xml_bytes): tuple[list[RawSection], list[str]]

Depends on: xml.etree.ElementTree, rag.regulatory.parser.RawSection
Used by: services/regulatory_ingest.py (via detect_parser dispatch)

Design spec: docs/superpowers/specs/2026-04-14-phase-1-ecfr-pipeline-design.md
"""
```

**Verified schema (from live eCFR fetch of 36 CFR 800):**

| Structural level | Tag shape |
|---|---|
| PART (root) | `<DIV5 N="{part}" TYPE="PART" VOLUME="{n}" hierarchy_metadata="...">` |
| SUBPART | `<DIV6 N="{letter}" TYPE="SUBPART" hierarchy_metadata="...">` |
| SECTION | `<DIV8 N="{section_num}" TYPE="SECTION" hierarchy_metadata="...">` |
| APPENDIX | Presumed `<DIV9 N="{letter}" TYPE="APPENDIX">` — verify during implementation |

**`hierarchy_metadata` attribute** is a JSON string containing `path` and `citation` fields. Parser uses the `citation` value directly rather than constructing citation strings — eliminates drift risk.

**Walk order:**
1. Root `<DIV5>` — confirm `TYPE="PART"`, extract `N` as part number, parse `hierarchy_metadata` for citation context
2. Skip part-level metadata: `<HEAD>` (part name — captured as `part_title`), `<AUTH>`, `<SOURCE>` (not emitted as warnings — they're expected structural tags)
3. Iterate descendants of `<DIV5>`:
   - On `<DIV6 TYPE="SUBPART">`: set subpart context, recurse into children
   - On `<DIV8 TYPE="SECTION">`: emit one `RawSection`
   - On `<DIV9 TYPE="APPENDIX">` (if encountered): emit one `RawSection` with section = `f"App{N}"`
   - On unexpected element: append a human-readable message to the returned `list[str]` warnings AND log at `warning` level; skip the element

**Warning-vs-log convention** (applies to all tag-handling rules below):
- "append to warnings" = the message is returned in the `list[str]` from `parse_ecfr_xml` (so callers and the DB `parser_warnings` column see it)
- "log at debug/warning level" = Python logger only, not returned
- Default for unrecognized structural tags: append to warnings + log at `warning`
- Default for recognized-but-skipped formatting tags: log at `debug` only

**Section body extraction:**
- Iterate `<P>` children
- Inline handling:
  - `<I>text</I>` → `*text*` (markdown italics) or plain text
  - `<E T="04">text</E>` → `**text**` (markdown bold) or plain text
  - `<SU>text</SU>` → `^text^` or strip (superscripts, usually footnote markers)
  - `<FTREF/>` → strip (footnote references; the body tag `<FTNT>` captured separately)
  - `<CITA>` → stripped from body; optionally captured in metadata
- `<PSPACE>` is **not** body text (appears only in `<AUTH>`/`<SOURCE>` blocks — part-level metadata)

**Defensively handled (may appear in other parts, not observed in 36 CFR 800):**
- `<FTNT>` — confirmed present in 23 CFR 771; capture body text as an annotation, emit warning
- `<AMDDATE>` — strip from body, log at debug level
- `<EDNOTE>` — strip from body, log at debug level

**`RawSection` population** (reusing existing dataclass):
- `document_type = DocumentType.CFR_REGULATION` (reuse existing enum — no new value)
- `section` = `N` attribute from `<DIV8>` (e.g., `"800.3"`)
- `title` = `<HEAD>` text with leading `"§ 800.3"` stripped
- `body` = concatenated paragraph text
- `citation` = value from `hierarchy_metadata["citation"]` (e.g., `"36 CFR 800.3"`)
- `part` = root `<DIV5>` `N` attribute
- `part_title` = root `<DIV5>` `<HEAD>` text
- `effective_date` = passed from caller (the date used for the fetch)

### `backend/services/ecfr_ingest.py`

Orchestration layer. Separate module from `regulatory_ingest.py` to keep single-purpose files.

```python
"""Ingest a CFR part via the eCFR API into the regulatory RAG store.

Fetches XML, stages it in regulatory_sources, delegates to the
generalized ingest pipeline.

Public API:
  - ingest_ecfr_source(conn, *, title, part, date, embedding_provider,
                        correlation_id, trigger): source_id

Depends on:
  - api_clients.ecfr.fetch_ecfr_xml
  - db.regulatory_sources.upsert_ecfr_source
  - services.regulatory_ingest.ingest_source_sync

Used by: scripts/ingest_ecfr.py, routers (POST /api/sources/ecfr)

Design spec: docs/superpowers/specs/2026-04-14-phase-1-ecfr-pipeline-design.md
"""

def ingest_ecfr_source(
    conn,
    *,
    title: int,
    part: str,
    date: str = "current",
    embedding_provider,
    correlation_id: str | None = None,
    trigger: str = "cli",     # 'cli' | 'api' — recorded in audit log
) -> str:
    """Fetch eCFR XML, upsert source row, run ingest pipeline.

    Returns the source_id (UUID) of the created or updated source row.

    Writes one regulatory_ingest_log row on entry (status='started')
    and updates it on completion ('ready' or 'failed').
    """
```

`upsert_ecfr_source` is a new helper in `backend/db/regulatory_sources.py`:

```python
def upsert_ecfr_source(
    conn,
    *,
    source_type: str,         # always "ecfr" for this helper
    cfr_title: int,
    cfr_part: str,
    effective_date: date | None,
    content_type: str,
    filename: str,
    bytes: bytes,
) -> str:
    """Insert or update-in-place based on identity tuple.

    Uses the partial unique index regulatory_sources_identity_idx.
    Returns the UUID of the row. On update, refreshes bytes/sha256/
    size_bytes/timestamps while keeping the same id — which lets
    cascade_delete_chunks then remove stale chunks by source_id.
    """
```

## Backend — Trigger Surfaces

### `scripts/ingest_ecfr.py` — CLI

```
Usage:
  python scripts/ingest_ecfr.py --title 36 --part 800
                                [--date current|YYYY-MM-DD]
                                [--embedding-provider gemini]
                                [--db-url $DATABASE_URL]
                                [--dry-run]

  # Batch mode
  python scripts/ingest_ecfr.py --from-file parts.yaml
```

**Batch YAML format:**
```yaml
- title: 23
  part: "771"
- title: 36
  part: "800"
- title: 33
  part: "323"
```

Each tuple is a separate `ingest_ecfr_source` call with its own correlation_id. One failure does not halt the batch — failures report at the end.

**`--dry-run` behavior:** fetches XML, parses, chunks, prints a summary (section count, chunk count, token distribution, warnings). Does not write to DB. Does not call the embedding provider.

Mirrors `scripts/ingest_regulations.py` structure. ~80–100 lines.

### `POST /api/sources/ecfr` — HTTP endpoint

New route. Placement depends on `main.py` size at implementation time — extract to `routers/ecfr.py` if the file is near its budget.

**Request body:**
```python
class EcfrIngestRequest(BaseModel):
    """Request body for POST /api/sources/ecfr."""
    title: int = Field(
        ..., ge=1, le=50,
        description="CFR title number (1-50). Example: 40 for 40 CFR, 36 for 36 CFR.",
    )
    part: str = Field(
        ..., min_length=1, max_length=20,
        description="CFR part identifier. String, not int, because parts can have suffixes.",
    )
    date: str | None = Field(
        None,
        pattern=r"^(current|\d{4}-\d{2}-\d{2})$",
        description=(
            "Version to fetch. 'current' (default) resolves to the latest valid "
            "amendment date. An ISO date fetches the snapshot from that date "
            "(Phase 1.5 feature — schema ready, write-path disabled in Phase 1)."
        ),
    )
```

**Response (immediate, 200):**
```json
{
  "source_id": "uuid-here",
  "correlation_id": "abc12345",
  "status": "embedding",
  "message": "eCFR ingest started for title 36 part 800"
}
```

**Flow:**
1. Authenticate — match whatever `POST /api/sources` does today (verify at implementation).
2. Pydantic validation.
3. **Synchronous:** fetch XML, upsert `regulatory_sources`. Failures here return HTTP errors immediately — this part must not be hidden in a background task.
4. **Background:** `ingest_source_sync` via FastAPI `BackgroundTask`. Response returns immediately with `source_id` + `correlation_id`.
5. Client polls existing `GET /api/sources/{id}` endpoint for progress.

**Error responses:**
- `400` — Pydantic validation failure
- `404` — eCFR API returns 404 for the tuple
- `409` — re-ingest already in progress for same `(source_type, cfr_title, cfr_part, effective_date)` (existing row has `status="embedding"`)
- `502` — eCFR API unreachable after retries
- `500` — DB error during upsert

## Frontend — Chunks Inspector

### New backend endpoints

**1. `GET /api/sources`** — list sources for the filter dropdown.

```json
[
  {
    "id": "uuid",
    "filename": "ecfr_title-36_part-800_current.xml",
    "source_type": "ecfr",
    "cfr_title": 36,
    "cfr_part": "800",
    "effective_date": null,
    "chunk_count": 147,
    "status": "ready"
  }
]
```

Check at implementation whether this endpoint already exists; if yes, verify shape matches and reuse.

**2. `GET /api/sources/{source_id}/chunks?page=&per_page=`** — untruncated chunks for one source.

```json
{
  "source_id": "uuid",
  "page": 1,
  "per_page": 25,
  "total": 147,
  "total_pages": 6,
  "chunks": [
    {
      "id": "chunk-uuid",
      "chunk_index": 0,
      "citation": "36 CFR §800.3",
      "breadcrumb": "36 CFR Part 800 — Protection of Historic Properties › §800.3 Initiation of the section 106 process",
      "content": "…full untruncated chunk text…",
      "token_count": 842,
      "metadata": { /* full JSONB passthrough */ }
    }
  ]
}
```

Uses the new typed `source_id` column for the WHERE clause — indexed lookup.

### `components/ChunksView.jsx`

New file, ~250 lines.

**Activation:** `TableDetail.jsx` checks `tableName`. If `regulatory_chunks`, renders `<ChunksView onBack={onBack} />` instead of the generic table body. Every other table uses the existing generic viewer, unchanged.

**Layout:**
```
┌─ ChunksView ────────────────────────────────────────┐
│  [← BACK]  regulatory_chunks  [source: All ▾]       │
├─────────────────────────────────────────────────────┤
│  Showing all sources — 350 chunks                   │
│                                                     │
│  [▸] §800.3  Initiation of the section 106 process  │
│       36 CFR Part 800 › §800.3 • 842 tokens        │
│                                                     │
│  [▸] §800.4  Identification of historic properties  │
│       36 CFR Part 800 › §800.4 • 1,203 tokens      │
│                                                     │
│  [▾] §800.5  Assessment of adverse effects          │
│       36 CFR Part 800 › §800.5 • 756 tokens        │
│       ┌──────────────────────────────────────┐     │
│       │  Full chunk content rendered here…   │     │
│       └──────────────────────────────────────┘     │
│                                                     │
│  [← PREV]   Page 1 of 14   [NEXT →]                │
└─────────────────────────────────────────────────────┘
```

**Behavior:**
- Source filter dropdown populated from `GET /api/sources`. Default: "All sources." Display label: `"36 CFR Part 800 (ecfr)"` for eCFR sources, `"NEPA-40CFR1500_1508.pdf (pdf_upload)"` for uploaded PDFs.
- When a specific source is selected, fetches `GET /api/sources/{id}/chunks`.
- When "All sources" is selected, falls back to the existing `GET /api/db/tables/regulatory_chunks` endpoint.
- Each row: compact one-line summary (citation + breadcrumb + token count), chevron on left.
- Click row or chevron → expands inline, renders full content in a monospace block. Chevron rotates.
- **Default state: all rows collapsed.**
- Pagination identical to existing `TableDetail`.

**Reused styles:** `var(--font-mono)`, `var(--green-primary)`, `var(--border)`, `var(--bg-card)`, back-button and pagination patterns from `TableDetail`. No new CSS primitives.

## Agent-Friendliness, Developer-Friendliness, Auditability

Commitments that shape how the code gets written, not afterthoughts.

### Predictable structure

Every source type follows the same file layout (stated explicitly in `docs/ingest-ecfr.md`):

| Concern | Path | Function name |
|---|---|---|
| HTTP client | `api_clients/{source}.py` | `fetch_{source}_{resource}(...)` |
| Parser | `rag/regulatory/parser_{source}.py` | `parse_{source}_{format}(...)` |
| Ingest service | `services/{source}_ingest.py` | `ingest_{source}_source(...)` |
| CLI | `scripts/ingest_{source}.py` | — |
| Endpoint | `POST /api/sources/{source}` | — |
| Tests | `tests/test_{module_name}.py` | — |

Phase 2 (Federal Register) follows this template verbatim.

**File size targets.** Each new file aims for <400 lines. Splits use the established pattern (e.g., `parser_ecfr_sections.py` + `parser_ecfr_normalize.py`). Noted in the spec so future changes have a guardrail.

### Self-documenting code

- **Module-header template** on every new file: purpose, public API, depends-on, used-by, spec back-reference.
- **Full type annotations** on every new function.
- **Extension-point markers** as grep-able comments at dispatch points.
- **No magic strings/numbers** — module-level constants (`_ECFR_BASE_URL`, `_DEFAULT_PAGE_SIZE`, etc.)

### End-to-end traceability

- Correlation IDs thread through CLI → service function → HTTP client → parser → orchestrator.
- HTTP endpoint **returns correlation_id in response body** (new — existing code keeps it in logs only).
- Every log line from new code includes structured fields: `cid`, `source_id`, `source_type`, `cfr_title`, `cfr_part`.
- Error messages include enough context to fix without reading source — e.g. `raise ValueError(f"date must be 'current' or ISO YYYY-MM-DD, got: {date!r}")`.

### Audit surface

- **Migration discipline:** each schema change is a named function in the existing migrations package. Docstring states: what it does, idempotency behavior, rollback note.
- **`regulatory_ingest_log`** table records every ingest attempt (start + completion). Enables "who ingested what when."
- **PR discipline:** 5 rollout steps = 5 separate PRs (or well-separated commits). Each references this spec path. Commit subjects follow the existing convention (`feat(db):`, `feat(api):`, `feat(frontend):`).

## Testing Strategy

### Parser unit tests — `backend/tests/test_parser_ecfr.py`

Golden-file tests against 3 fixture XMLs committed to `backend/tests/fixtures/ecfr/`:
- `title-36_part-800.xml` (Section 106 — known good, verified during design)
- `title-23_part-771.xml` (FHWA NEPA — has `<FTNT>` and `<FTREF/>`)
- `title-33_part-323.xml` (CWA 404 — short baseline)

Each test parses the fixture and asserts: section count, first section's citation/title/pages, warnings list shape, stripping of `<CITA>`/`<FTREF/>`/`<SU>` from body.

Edge-case tests:
- Empty part → raises with actionable error
- Malformed XML → raises with actionable error
- `hierarchy_metadata` missing → falls back to constructing citation manually + logs warning

Mirrors `test_pa_code_parser.py` patterns.

### HTTP client test — `backend/tests/test_ecfr_client.py`

`httpx.MockTransport` returns canned XML bytes. Assertions: URL pattern correct, retry loop behavior on 500, raises on persistent failure, correlation_id flows to logs. No network access.

### Service function test — `backend/tests/test_ecfr_ingest.py`

Mocks `fetch_ecfr_xml` and `ingest_source_sync`. Asserts:
- `upsert_ecfr_source` called with correct tuple
- Re-running with same `(title, part, date)` reuses same `source_id`
- `regulatory_ingest_log` row written on entry + updated on completion

Integration-adjacent test (uses real test DB if available, following `test_regulatory_sources_repo.py` pattern).

### Pipeline integration test — `backend/tests/test_regulatory_ingest_xml.py`

Full path: fixture XML → `upsert_ecfr_source` → `ingest_source_sync` with `content_type="application/xml"` → assert chunks land in `regulatory_chunks` with correct typed `source_id` and metadata. Uses a mock embedding provider (fixed-dim random vectors).

### Frontend tests — `frontend/src/components/ChunksView.test.jsx`

- Renders with mocked `/api/sources` → dropdown populates
- Selecting a source triggers fetch to `/api/sources/{id}/chunks`
- Chevron click expands content; second click collapses
- Default state: all rows collapsed
- Pagination fires with correct page numbers

Mirrors `SourcesModal.test.jsx` pattern.

### Migration safety test — `backend/tests/test_migration_sources_columns.py`

- Applies the migration to a fresh schema
- Inserts a pre-existing PDF-shaped row (no `cfr_title`, no `effective_date`) → succeeds
- Inserts two eCFR rows with same tuple → second fails with uniqueness error
- Backfill test: pre-seeds chunks with `metadata->>'source_id'` set, runs backfill, asserts typed column populated

### Explicitly not tested

- Real eCFR API calls (mocked only)
- Embedding quality on eCFR content (retrieval quality, not ingest)
- Performance benchmarks (Phase 1 volume doesn't warrant)
- Concurrent ingest collision (single-tenant admin tool)

## Rollout Plan

Five steps, each independently verifiable and revertible.

**Step 1 — Schema migration only** (no code paths use the new columns yet)
- Adds columns with defaults, partial unique index, typed `source_id` on chunks, `regulatory_ingest_log` table, JSONB→typed backfill
- Verify: `SELECT COUNT(*) FROM regulatory_chunks WHERE source_id IS NULL` returns 0
- Deploy-safe: existing PDF ingest continues working with default column values

**Step 2 — Pipeline generalization** (`detect_parser` takes `content_type`)
- Existing PDF rows have `content_type='application/pdf'` by default → identical code path
- Verify: upload a PDF through existing `POST /api/sources`; ingests successfully (regression check)

**Step 3 — eCFR client + parser + service function**
- `api_clients/ecfr.py`, `parser_ecfr.py`, `services/ecfr_ingest.py`, `upsert_ecfr_source` helper, `regulatory_ingest_log` writer
- No new trigger surface yet — service function exists but isn't called
- Verify via the CLI in step 4

**Step 4 — Trigger surfaces**
- `scripts/ingest_ecfr.py` and `POST /api/sources/ecfr`
- Smoke: `python scripts/ingest_ecfr.py --title 36 --part 800 --dry-run` on dev DB
- Real: ingest 23 CFR 771, 36 CFR 800, 33 CFR 323 (order-independent)
- Curl test on the endpoint with the same tuples

**Step 5 — Chunks inspector frontend**
- `/api/sources` listing + `/api/sources/{id}/chunks` endpoints
- `ChunksView.jsx` component; `TableDetail.jsx` branches into it
- Verify: open DB viewer → click `regulatory_chunks` → dropdown shows 4 sources (3 eCFR + existing PDF) → pick one → rows render collapsed → expand works

### Rollback

Each step is independently reversible:
- Step 5 → revert frontend commit. Everything else unaffected.
- Step 4 → revert endpoint + CLI. Service function untouched but not called.
- Step 3 → revert new modules. Pipeline generalization (step 2) still handles PDFs correctly.
- Step 2 → revert one `detect_parser` signature change.
- Step 1 → schema columns stay (NULL-able with defaults). Rollback only required if backfill went wrong, caught by step-1 verification.

## Documentation Plan

### 1. This spec
`docs/superpowers/specs/2026-04-14-phase-1-ecfr-pipeline-design.md`. Committed to the branch. Authoritative decision record.

### 2. Operator guide
New file: `docs/ingest-ecfr.md`. Covers:
- Prerequisites (env, DB migration applied, embedding provider)
- CLI usage with every flag documented + examples
- Example YAML for `--from-file`
- HTTP endpoint usage: curl example, Swagger UI link, expected response, error codes
- How to verify ingest succeeded
- Re-ingestion semantics
- Troubleshooting common failures
- "Adding a new source type" — procedure for Phase 2/3 maintainers, referencing the naming conventions

### 3. README.md
Brief "Regulatory Source Ingestion" section. Lists supported source types; points at `docs/ingest-ecfr.md` for detail. Does not bloat with operator-level content.

### 4. Module-level docstrings
Comprehensive on every new file. Template includes: purpose, public API, depends-on, used-by, spec back-reference. Function-level docstrings on every public API function.

### 5. Pydantic schema docstrings
`EcfrIngestRequest` field-level descriptions feed FastAPI's auto-generated `/docs` OpenAPI page.

### 6. Inline code comments
Only where the *why* isn't obvious from the code. Specifically required at:
- The partial unique index on `regulatory_sources` (explain PDF exclusion)
- The typed `source_id` column on chunks (prefer-over-JSONB note)
- The `detect_parser` dispatch (extension point)
- Any regex/XML tag with a non-obvious eCFR-schema reason

### 7. Migration comments
Each migration function has a docstring: what it does, idempotency, rollback behavior.

### Explicitly not included
- ADR format (this spec is the ADR)
- Tutorial videos / screencasts
- Hand-written API reference (FastAPI `/docs` is the reference)

## Definition of Done

- [ ] All migrations applied; backfill verified (zero NULL `source_id` on chunks)
- [ ] `pytest backend/tests/test_parser_ecfr.py` passes with 3 fixture parts
- [ ] `pytest backend/tests/test_ecfr_client.py` passes
- [ ] `pytest backend/tests/test_ecfr_ingest.py` passes
- [ ] `pytest backend/tests/test_regulatory_ingest_xml.py` passes
- [ ] `pytest backend/tests/test_migration_sources_columns.py` passes
- [ ] `npm test -- ChunksView` passes
- [ ] Existing PDF ingest regression: upload a PDF through `POST /api/sources` and verify it ingests successfully
- [ ] 23 CFR 771, 36 CFR 800, 33 CFR 323 all ingested via eCFR, each with `status="ready"` and a `regulatory_ingest_log` row
- [ ] Chunks inspector renders all 4 sources (3 eCFR + existing 40 CFR 1500–1508 PDF) in the dropdown
- [ ] Expand/collapse works; default is collapsed
- [ ] `docs/ingest-ecfr.md` written and covers all sections listed in Documentation Plan §2
- [ ] README.md updated
- [ ] Two known unknowns (canonical "current" URL, APPENDIX tag shape) resolved — implementation notes added to `api_clients/ecfr.py` and `parser_ecfr.py` module docstrings

## Open Questions Resolved During Brainstorming

- **Three ingest pipelines vs. one generalized?** → One generalized. Only parser selection varies. Answer lives in the "Pipeline generalization" section above.
- **Gray area: will state PDFs force a RawSection refactor?** → Low-medium risk, handled as Phase 3 with real data. Hedge now: Phase 3 chunker must respect atomic markdown blocks (tables, code fences). Noted for Phase 3.
- **Point-in-time: build now or defer?** → Schema now (C), code write path Phase 1.5.
- **Re-ingest strategy?** → Upsert in place keyed on tuple identity (B).
- **Which CFR parts for Phase 1?** → 23 CFR 771, 36 CFR 800, 33 CFR 323 — net-new sources.
- **Touch existing 40 CFR 1500–1508 PDF?** → No. Migration is a separate follow-up.
- **Chunks inspector scope?** → Include in Phase 1 (X). Necessary to validate Phase 1's output.
- **Pipeline abstraction level?** → Approach 1 (minimal surgery, inline dispatch). Promote to registry when format count justifies it.
- **Trigger surface?** → Both CLI and HTTP endpoint (D), sharing one service function.
- **Audit log table?** → Include in Phase 1. History endpoint deferred.
