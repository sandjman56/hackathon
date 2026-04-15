# EIS Evaluation Ingestion Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an EIS PDF ingest pipeline (parse → chunk → embed → store) that runs automatically when a user uploads an EIS on the Evaluations page, writes labeled chunks to a new `evaluation_chunks` table, and exposes a retrieval endpoint plus a chunks inspector UI.

**Architecture:** Sibling pipeline to the existing `regulatory_ingest` — reuses the async embedder and tiktoken-based token counting, adds an EIS-specific pymupdf parser (heading-aware with page-group fallback) and token-aware chunker. Upload triggers a FastAPI `BackgroundTasks` job that updates status/progress on the `evaluations` row. Frontend adds per-row polling, a RETRY button for failed ingests, and a paginated `EvaluationChunksView` inspector. Similarity search scoped to a single evaluation is exposed via `POST /api/evaluations/{id}/search`.

**Tech Stack:** FastAPI, psycopg2, pgvector (HNSW), pymupdf, tiktoken, React 18 + Vite, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-04-15-eis-eval-pipeline-design.md`

---

## File Structure

**New backend modules:**
- `backend/rag/_tokens.py` — shared `count_tokens` helper extracted from regulatory chunker (avoids circular import when both chunkers share the tiktoken encoder).
- `backend/rag/evaluation/__init__.py`
- `backend/rag/evaluation/parser.py` — `parse_eis_pdf(blob) -> tuple[list[RawEisSection], list[str]]`
- `backend/rag/evaluation/chunker.py` — `chunk_eis_sections(sections) -> list[EisChunk]`
- `backend/rag/evaluation/store.py` — DDL, upsert, search
- `backend/services/evaluation_ingest.py` — orchestrator, mirrors `regulatory_ingest.py`
- `backend/db/evaluations.py` — CRUD + status/progress helpers (extracts inline SQL from `main.py`)

**Modified backend modules:**
- `backend/main.py` — lifespan (init table + sweep + `ALTER TABLE evaluations`), replace inline evaluations SQL with `db.evaluations` calls, add new endpoints.
- `backend/rag/regulatory/chunker.py` — re-export `count_tokens` from `rag/_tokens.py` for backward compat.

**New frontend modules:**
- `frontend/src/components/EvaluationChunksView.jsx`
- `frontend/src/components/EvaluationChunksView.test.jsx`

**Modified frontend modules:**
- `frontend/src/components/EvaluationsView.jsx` — polling, status pill, progress bar, RETRY, row-click navigation.
- `frontend/src/App.jsx` — `view='evaluation-chunks'` state + route.

**Tests:**
- `backend/tests/fixtures/eis/` — small fixture PDFs (generated via pymupdf in a conftest helper, no real EIS required for CI).
- `backend/tests/test_eis_parser.py`
- `backend/tests/test_eis_chunker.py`
- `backend/tests/test_evaluation_store.py`
- `backend/tests/test_evaluation_ingest.py`
- `backend/tests/test_evaluations_api.py`
- `backend/tests/test_evaluation_startup_sweep.py`
- `frontend/src/components/EvaluationsView.test.jsx` — new file (modify component → new test file)

**Docs:**
- `docs/eval-pipeline.md` — operator guide
- `README.md` — new subsection linking to it

---

## Task 1: Extract shared `count_tokens` helper

**Files:**
- Create: `backend/rag/_tokens.py`
- Modify: `backend/rag/regulatory/chunker.py`

- [ ] **Step 1: Write the helper**

Create `backend/rag/_tokens.py`:

```python
"""Shared tokenizer helper used by regulatory and evaluation chunkers.

Both chunkers need the same cl100k_base encoder. Importing from either
chunker module would create a circular import via their parsers, so the
encoder lives here.
"""
from __future__ import annotations

import tiktoken

_ENCODER = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Return the cl100k_base token count for ``text``."""
    return len(_ENCODER.encode(text))


def encode(text: str) -> list[int]:
    return _ENCODER.encode(text)


def decode(tokens: list[int]) -> str:
    return _ENCODER.decode(tokens)
```

- [ ] **Step 2: Re-wire regulatory chunker to use the helper**

Edit `backend/rag/regulatory/chunker.py`. Replace the existing `_ENCODER`, `count_tokens`, and `_decode` definitions (roughly lines 56-67) with:

```python
from rag._tokens import count_tokens, encode as _encode, decode as _decode  # noqa: F401
```

Leave the rest of the file unchanged. Any internal uses of `_ENCODER.encode(...)` become `_encode(...)`; any internal uses of `_ENCODER.decode(...)` become `_decode(...)`.

- [ ] **Step 3: Run regulatory chunker tests to verify no regression**

Run: `cd backend && pytest tests/test_regulatory_parser.py tests/test_ingest_ecfr_cli.py tests/test_regulatory_ingest_xml.py tests/test_regulatory_ingest.py tests/test_regulatory_embedder.py -x`
Expected: PASS (no behavior change — same encoder).

- [ ] **Step 4: Commit**

```bash
git add backend/rag/_tokens.py backend/rag/regulatory/chunker.py
git commit -m "refactor(rag): extract shared count_tokens helper"
```

---

## Task 2: EIS parser — fixture PDF builder

**Files:**
- Create: `backend/tests/fixtures/eis/__init__.py`
- Create: `backend/tests/fixtures/eis/build_sample.py`
- Create: `backend/tests/fixtures/eis/conftest.py`

The real FEIS sample PDFs in `~/Downloads/` are too large and not in the repo. We generate a deterministic synthetic EIS PDF with pymupdf at test time — same rendering primitives the real parser will consume.

- [ ] **Step 1: Create the fixture builder module**

Create `backend/tests/fixtures/eis/__init__.py` (empty) and `backend/tests/fixtures/eis/build_sample.py`:

```python
"""Builds a synthetic EIS-style PDF in memory for parser tests.

The PDF mirrors the font-hierarchy conventions of a real FEIS chapter:
- Chapter heading: bold, 18pt, "Chapter 4: Environmental Resources"
- Section heading: bold, 14pt, "4.1 Water Resources"
- Subsection heading: bold, 12pt, "4.1.1 Surface Water"
- Body text: regular, 11pt
- Page footer: regular, 9pt, centered (parser must ignore)
"""
from __future__ import annotations

import pymupdf


BODY_FONT = "helv"
BOLD_FONT = "hebo"


def build_sample_eis_bytes() -> bytes:
    """Return raw bytes of a 3-chapter synthetic EIS PDF."""
    doc = pymupdf.open()

    def add_page(items: list[tuple[str, float, bool]]) -> None:
        page = doc.new_page(width=612, height=792)
        y = 72
        for text, size, bold in items:
            font = BOLD_FONT if bold else BODY_FONT
            page.insert_text((72, y), text, fontsize=size, fontname=font)
            y += size + 8
        page.insert_text((300, 770), f"Page {doc.page_count}",
                         fontsize=9, fontname=BODY_FONT)

    # --- Chapter 1
    add_page([
        ("Chapter 1: Purpose and Need", 18, True),
        ("1.1 Project Overview", 14, True),
        ("The proposed action would construct a new highway corridor "
         "across the eastern valley.", 11, False),
        ("The corridor is approximately 12 miles long.", 11, False),
        ("1.2 Need for the Project", 14, True),
        ("Traffic volumes have grown 34% over the last decade.",
         11, False),
    ])

    # --- Chapter 4
    add_page([
        ("Chapter 4: Environmental Resources", 18, True),
        ("4.1 Water Resources", 14, True),
        ("The project area includes three named streams and six "
         "jurisdictional wetland areas.", 11, False),
        ("4.1.1 Surface Water", 12, True),
        ("Streams in the project area are classified as warm-water "
         "fisheries under state regulation.", 11, False),
    ])
    add_page([
        ("4.1.2 Groundwater", 12, True),
        ("Primary aquifers beneath the corridor are confined "
         "sandstone units with recharge from surface infiltration.",
         11, False),
        ("4.2 Air Quality", 14, True),
        ("The project area is in attainment for all criteria "
         "pollutants.", 11, False),
    ])

    # --- Chapter 7
    add_page([
        ("Chapter 7: Effects", 18, True),
        ("7.1 Direct Effects", 14, True),
        ("Construction would permanently convert 240 acres of "
         "undeveloped land.", 11, False),
    ])

    buf = doc.write()
    doc.close()
    return bytes(buf)
```

- [ ] **Step 2: Create pytest fixture**

Create `backend/tests/fixtures/eis/conftest.py`:

```python
import pytest

from tests.fixtures.eis.build_sample import build_sample_eis_bytes


@pytest.fixture(scope="session")
def sample_eis_bytes() -> bytes:
    return build_sample_eis_bytes()
```

- [ ] **Step 3: Smoke test the builder**

Run: `cd backend && python -c "from tests.fixtures.eis.build_sample import build_sample_eis_bytes; b = build_sample_eis_bytes(); assert b.startswith(b'%PDF'); print(f'OK: {len(b)} bytes')"`
Expected: `OK: <some positive number> bytes`

- [ ] **Step 4: Commit**

```bash
git add backend/tests/fixtures/eis/
git commit -m "test(eis): add synthetic EIS PDF fixture builder"
```

---

## Task 3: EIS parser — data classes and heading regex

**Files:**
- Create: `backend/rag/evaluation/__init__.py`
- Create: `backend/rag/evaluation/parser.py`
- Create: `backend/tests/test_eis_parser.py`

- [ ] **Step 1: Write the failing test**

Create `backend/rag/evaluation/__init__.py` (empty).

Create `backend/tests/test_eis_parser.py`:

```python
from rag.evaluation.parser import (
    HEADING_RE,
    RawEisSection,
    classify_heading,
)


def test_heading_regex_matches_numbered():
    assert HEADING_RE.match("4.2.3 Groundwater")
    assert HEADING_RE.match("1.1 Project Overview")
    assert HEADING_RE.match("7 Effects")  # single-level


def test_heading_regex_rejects_non_headings():
    assert HEADING_RE.match("This sentence describes 4.2.3 of the proposal.") is None
    assert HEADING_RE.match("Traffic volumes have grown 34% over the last decade.") is None


def test_classify_heading_chapter():
    kind, number, title = classify_heading("Chapter 4: Environmental Resources", size=18.0, is_bold=True, body_size=11.0)
    assert kind == "chapter"
    assert number == "4"
    assert title == "Environmental Resources"


def test_classify_heading_section():
    kind, number, title = classify_heading("4.2 Water Resources", size=14.0, is_bold=True, body_size=11.0)
    assert kind == "section"
    assert number == "4.2"
    assert title == "Water Resources"


def test_classify_heading_body_text_returns_none():
    result = classify_heading("Streams in the project area are classified as warm-water fisheries.",
                              size=11.0, is_bold=False, body_size=11.0)
    assert result is None


def test_raw_eis_section_dataclass():
    s = RawEisSection(
        chapter="4", section_number="4.2.3",
        section_title="Groundwater",
        breadcrumb="Chapter 4: Environmental Resources > 4.2 Water Resources > 4.2.3 Groundwater",
        body="Aquifer body text.",
        page_start=12, page_end=12,
    )
    assert s.chapter == "4"
    assert s.breadcrumb.endswith("Groundwater")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_eis_parser.py -x`
Expected: FAIL with `ModuleNotFoundError: No module named 'rag.evaluation.parser'`.

- [ ] **Step 3: Write the data class and heading helpers**

Create `backend/rag/evaluation/parser.py`:

```python
"""PDF -> ordered list of RawEisSection records for EIS documents.

Unlike the regulatory parser, which is CFR-aware, this parser targets
FEIS chapter PDFs: numbered hierarchical headings (1, 1.1, 1.1.1, ...)
rendered at larger or bolder fonts than the body.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import pymupdf

logger = logging.getLogger("eia.rag.evaluation.parser")

# Matches a numbered heading that starts a block, e.g. "4.2.3 Groundwater".
# Anchored at start, requires at least one space between number and title.
HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,3})\s+(\S.*\S|\S)\s*$")

# Matches "Chapter N: Title" or "Chapter N Title"
CHAPTER_RE = re.compile(r"^Chapter\s+(\d+)\s*[:\-]?\s*(.+?)\s*$", re.IGNORECASE)


@dataclass
class RawEisSection:
    """One contiguous section pulled from an EIS PDF."""
    chapter: Optional[str]
    section_number: Optional[str]
    section_title: str
    breadcrumb: str
    body: str
    page_start: int
    page_end: int
    has_table_hint: bool = False


def classify_heading(
    text: str, *, size: float, is_bold: bool, body_size: float,
) -> Optional[tuple[str, Optional[str], str]]:
    """Classify a text block as ``(kind, number, title)`` or None.

    ``kind`` is one of ``"chapter"``, ``"section"``. Chapters match the
    ``CHAPTER_RE`` pattern regardless of font; sections require either a
    size bump (>1.15x body) or bold weight AND a numbered-heading match.
    """
    stripped = text.strip()
    if not stripped:
        return None

    m = CHAPTER_RE.match(stripped)
    if m:
        return ("chapter", m.group(1), m.group(2).strip())

    is_large = size > body_size * 1.15
    if not (is_large or is_bold):
        return None

    m = HEADING_RE.match(stripped)
    if m:
        return ("section", m.group(1), m.group(2).strip())
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_eis_parser.py -x`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/rag/evaluation/__init__.py backend/rag/evaluation/parser.py backend/tests/test_eis_parser.py
git commit -m "feat(eis-parser): add RawEisSection + heading classifier"
```

---

## Task 4: EIS parser — end-to-end `parse_eis_pdf`

**Files:**
- Modify: `backend/rag/evaluation/parser.py`
- Modify: `backend/tests/test_eis_parser.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_eis_parser.py`:

```python
from rag.evaluation.parser import parse_eis_pdf


def test_parse_eis_pdf_builds_breadcrumbs(sample_eis_bytes):
    sections, warnings = parse_eis_pdf(sample_eis_bytes)
    assert len(sections) >= 5  # 3 chapters x at least one leaf each

    # Find the groundwater subsection
    gw = next((s for s in sections if s.section_number == "4.1.2"), None)
    assert gw is not None, [s.section_number for s in sections]
    assert gw.chapter == "4"
    assert gw.section_title == "Groundwater"
    assert "Chapter 4" in gw.breadcrumb
    assert "4.1 Water Resources" in gw.breadcrumb
    assert "4.1.2 Groundwater" in gw.breadcrumb
    assert "aquifer" in gw.body.lower() or "sandstone" in gw.body.lower()


def test_parse_eis_pdf_handles_empty_document():
    import pymupdf
    doc = pymupdf.open()
    doc.new_page()
    blob = bytes(doc.write())
    doc.close()
    sections, warnings = parse_eis_pdf(blob)
    assert sections == []
    assert any("no headings detected" in w.lower() for w in warnings)


def test_parse_eis_pdf_page_ranges_monotonic(sample_eis_bytes):
    sections, _ = parse_eis_pdf(sample_eis_bytes)
    for s in sections:
        assert s.page_start <= s.page_end
        assert s.page_start >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_eis_parser.py -x`
Expected: FAIL with `ImportError: cannot import name 'parse_eis_pdf'`.

- [ ] **Step 3: Implement `parse_eis_pdf`**

Append to `backend/rag/evaluation/parser.py`:

```python
_TABLE_HINT_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


def _iter_blocks(doc: "pymupdf.Document"):
    """Yield ``(page_num, text, max_size, is_bold)`` for each text block.

    ``max_size`` is the largest font size seen in the block's spans; a
    block is ``is_bold`` if the majority of its character count is in a
    bold-weight span.
    """
    for page_idx, page in enumerate(doc, start=1):
        raw = page.get_text("dict")
        for block in raw.get("blocks", []):
            if block.get("type") != 0:  # 0 = text, 1 = image
                continue
            lines = block.get("lines", [])
            spans = [sp for ln in lines for sp in ln.get("spans", [])]
            if not spans:
                continue
            text = " ".join(sp.get("text", "") for sp in spans).strip()
            if not text:
                continue
            max_size = max((sp.get("size", 0.0) for sp in spans), default=0.0)
            bold_chars = sum(
                len(sp.get("text", ""))
                for sp in spans
                if "Bold" in sp.get("font", "") or (sp.get("flags", 0) & 16)
            )
            total_chars = sum(len(sp.get("text", "")) for sp in spans)
            is_bold = total_chars > 0 and bold_chars * 2 >= total_chars
            yield (page_idx, text, max_size, is_bold)


def _modal_body_size(blocks: list[tuple[int, str, float, bool]]) -> float:
    """Return the most common font size among non-bold blocks (the body size)."""
    from collections import Counter
    sizes = [round(sz, 1) for (_p, _t, sz, bold) in blocks if not bold]
    if not sizes:
        return 11.0
    return Counter(sizes).most_common(1)[0][0]


def parse_eis_pdf(blob: bytes) -> tuple[list[RawEisSection], list[str]]:
    """Parse an EIS PDF into sections. Returns (sections, warnings)."""
    warnings: list[str] = []
    try:
        doc = pymupdf.open(stream=blob, filetype="pdf")
    except Exception as exc:
        return [], [f"failed to open pdf: {exc}"]

    try:
        blocks = list(_iter_blocks(doc))
    finally:
        doc.close()

    if not blocks:
        warnings.append("no text blocks found in pdf")
        return [], warnings

    body_size = _modal_body_size(blocks)
    logger.info("body_size detected: %.1fpt across %d blocks",
                body_size, len(blocks))

    # Walk blocks, maintain a 4-level heading stack.
    stack: list[tuple[str, Optional[str], str]] = []
    # current section accumulator
    cur_chapter: Optional[str] = None
    cur_number: Optional[str] = None
    cur_title: str = ""
    cur_breadcrumb: str = ""
    cur_body: list[str] = []
    cur_page_start: int = 0
    cur_page_end: int = 0
    cur_has_table = False

    sections: list[RawEisSection] = []

    def flush():
        nonlocal cur_body, cur_has_table
        if cur_title and cur_body:
            sections.append(RawEisSection(
                chapter=cur_chapter,
                section_number=cur_number,
                section_title=cur_title,
                breadcrumb=cur_breadcrumb,
                body="\n".join(cur_body).strip(),
                page_start=cur_page_start,
                page_end=cur_page_end,
                has_table_hint=cur_has_table,
            ))
        cur_body = []
        cur_has_table = False

    for page_num, text, size, is_bold in blocks:
        classified = classify_heading(
            text, size=size, is_bold=is_bold, body_size=body_size,
        )
        if classified is not None:
            # Close prior section before opening a new one.
            flush()
            kind, number, title = classified
            if kind == "chapter":
                stack = [(kind, number, f"Chapter {number}: {title}")]
                cur_chapter = number
                cur_number = None
                cur_title = f"Chapter {number}: {title}"
            else:
                depth = number.count(".")  # "4.1.2" -> depth 2
                # Pop stack down to chapter (keep) or deeper levels above this one.
                stack = [e for e in stack if e[0] == "chapter"
                         or (e[1] is not None and e[1].count(".") < depth)]
                stack.append((kind, number, f"{number} {title}"))
                # Chapter inferred from section number's first segment.
                first = number.split(".", 1)[0]
                cur_chapter = first
                cur_number = number
                cur_title = title
            cur_breadcrumb = " > ".join(label for _, _, label in stack)
            cur_page_start = page_num
            cur_page_end = page_num
        else:
            if cur_title:
                cur_body.append(text)
                cur_page_end = page_num
                if _TABLE_HINT_RE.search(text):
                    cur_has_table = True

    flush()

    if not sections:
        warnings.append("no headings detected — parser produced zero sections")

    return sections, warnings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_eis_parser.py -x`
Expected: PASS (all 8 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/rag/evaluation/parser.py backend/tests/test_eis_parser.py
git commit -m "feat(eis-parser): implement parse_eis_pdf with heading stack"
```

---

## Task 5: EIS chunker

**Files:**
- Create: `backend/rag/evaluation/chunker.py`
- Create: `backend/tests/test_eis_chunker.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_eis_chunker.py`:

```python
from rag.evaluation.chunker import (
    EisChunk,
    MAX_TOKENS,
    MIN_TOKENS,
    chunk_eis_sections,
    make_chunk_label,
)
from rag.evaluation.parser import RawEisSection


def _mk(section_number, body, pages=(1, 1), title="X",
        chapter=None, breadcrumb="X"):
    return RawEisSection(
        chapter=chapter or (section_number.split(".")[0] if section_number else None),
        section_number=section_number,
        section_title=title,
        breadcrumb=breadcrumb,
        body=body,
        page_start=pages[0],
        page_end=pages[1],
    )


def test_short_section_stays_whole():
    s = _mk("4.1", "Short body paragraph.")
    chunks = chunk_eis_sections([s])
    assert len(chunks) == 1
    assert chunks[0].total_chunks_in_section == 1
    assert chunks[0].chunk_index == 0


def test_long_section_splits():
    big_body = ("Paragraph line. " * 400)  # >> MAX_TOKENS
    s = _mk("4.2", big_body)
    chunks = chunk_eis_sections([s])
    assert len(chunks) > 1
    for i, c in enumerate(chunks):
        assert c.chunk_index == i
        assert c.total_chunks_in_section == len(chunks)


def test_paragraph_boundary_preferred_over_token_split():
    # Two clearly-delimited paragraphs
    body = ("first para " * 300) + "\n\n" + ("second para " * 300)
    s = _mk("5.1", body)
    chunks = chunk_eis_sections([s])
    assert len(chunks) >= 2
    # First chunk contains first-para text, not second
    assert "first" in chunks[0].body
    assert "second" not in chunks[0].body


def test_has_table_hint_propagates():
    s = _mk("6.1", "body | col1 | col2 |\n| a | b |\n")
    s.has_table_hint = True
    chunks = chunk_eis_sections([s])
    assert chunks[0].has_table is True


def test_make_chunk_label_format():
    s = _mk("4.2.3", "body", pages=(142, 143), title="Groundwater")
    label = make_chunk_label(
        filename="ch-4-environmental-resources.pdf",
        section=s, chunk_index=1, total=5,
    )
    assert label == "ch-4-environmental-resources §4.2.3 [p.142-143] (2/5)"


def test_make_chunk_label_no_section_number():
    s = _mk(None, "body", pages=(1, 2), title="Front matter")
    # section_number=None should trigger the title-based label
    s = RawEisSection(
        chapter=None, section_number=None, section_title="Front matter",
        breadcrumb="Front matter", body="body", page_start=1, page_end=2,
    )
    label = make_chunk_label(filename="intro.pdf", section=s, chunk_index=0, total=1)
    assert "§intro" in label or "§Front matter" in label
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_eis_chunker.py -x`
Expected: FAIL with `ModuleNotFoundError: No module named 'rag.evaluation.chunker'`.

- [ ] **Step 3: Implement the chunker**

Create `backend/rag/evaluation/chunker.py`:

```python
"""RawEisSection -> EisChunk conversion with token-aware splitting.

Short sections are kept whole (no sibling merging — EIS lacks the
definitions-style constraint that motivated it in the regulatory
chunker). Long sections are split on paragraph boundaries, then
token-split as a last resort with overlap between slices.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Optional

from rag._tokens import count_tokens, decode, encode
from rag.evaluation.parser import RawEisSection

logger = logging.getLogger("eia.rag.evaluation.chunker")

MIN_TOKENS = 200
MAX_TOKENS = 1500
TARGET_TOKENS = 700
OVERLAP_TOKENS = 90

_TABLE_HINT_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


@dataclass
class EisChunk:
    source: RawEisSection
    body: str
    chunk_index: int = 0
    total_chunks_in_section: int = 1
    has_table: bool = False
    token_count: int = 0
    extra: dict = field(default_factory=dict)


def _split_on_paragraphs(body: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return parts or [body]


def _token_split(body: str) -> list[str]:
    """Hard-split on tokens with overlap. Only called when paragraph split
    leaves a slice still over MAX_TOKENS."""
    toks = encode(body)
    if len(toks) <= MAX_TOKENS:
        return [body]
    slices: list[str] = []
    start = 0
    while start < len(toks):
        end = min(start + TARGET_TOKENS, len(toks))
        slices.append(decode(toks[start:end]))
        if end == len(toks):
            break
        start = end - OVERLAP_TOKENS
    return slices


def _pack_slices(body: str) -> list[str]:
    """Greedy-pack paragraphs into slices under MAX_TOKENS."""
    paragraphs = _split_on_paragraphs(body)
    slices: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for para in paragraphs:
        para_tokens = count_tokens(para)
        if para_tokens > MAX_TOKENS:
            if buf:
                slices.append("\n\n".join(buf))
                buf, buf_tokens = [], 0
            slices.extend(_token_split(para))
            continue
        if buf_tokens + para_tokens > MAX_TOKENS and buf:
            slices.append("\n\n".join(buf))
            buf, buf_tokens = [para], para_tokens
        else:
            buf.append(para)
            buf_tokens += para_tokens
    if buf:
        slices.append("\n\n".join(buf))
    return slices


def make_chunk_label(
    *, filename: str, section: RawEisSection,
    chunk_index: int, total: int,
) -> str:
    stem = PurePosixPath(filename).stem
    sec_key = section.section_number or (section.section_title or "intro").split()[0].lower()
    if not section.section_number:
        # Prefix with 'intro' for front-matter-ish sections
        sec_key = "intro"
    pages = (f"p.{section.page_start}-{section.page_end}"
             if section.page_end != section.page_start
             else f"p.{section.page_start}")
    return f"{stem} §{sec_key} [{pages}] ({chunk_index + 1}/{total})"


def chunk_eis_sections(sections: list[RawEisSection]) -> list[EisChunk]:
    chunks: list[EisChunk] = []
    for section in sections:
        body_tokens = count_tokens(section.body)
        if body_tokens <= MAX_TOKENS:
            slices = [section.body]
        else:
            slices = _pack_slices(section.body)
        total = len(slices)
        for i, slice_body in enumerate(slices):
            has_table = section.has_table_hint or bool(_TABLE_HINT_RE.search(slice_body))
            chunks.append(EisChunk(
                source=section,
                body=slice_body,
                chunk_index=i,
                total_chunks_in_section=total,
                has_table=has_table,
                token_count=count_tokens(slice_body),
            ))
    logger.info("chunked %d sections into %d chunks", len(sections), len(chunks))
    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_eis_chunker.py -x`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/rag/evaluation/chunker.py backend/tests/test_eis_chunker.py
git commit -m "feat(eis-chunker): token-aware splitter with chunk_label"
```

---

## Task 6: EIS store — DDL and upsert

**Files:**
- Create: `backend/rag/evaluation/store.py`
- Create: `backend/tests/test_evaluation_store.py`

The store uses pgvector and follows the pattern of `rag/regulatory/store.py`. Embedder compatibility: `embed_chunks()` reads `chunk.source.citation` only on error. We add a `citation` alias property to `EisChunk` to keep it happy.

- [ ] **Step 1: Add `citation` and `sources` compatibility properties to `EisChunk`**

Edit `backend/rag/evaluation/chunker.py`. Add to `EisChunk` class:

```python
@property
def citation(self) -> str:
    """Alias used by the shared embedder for error logging."""
    return (self.source.section_number
            or self.source.section_title
            or "<unknown>")

@property
def sources(self) -> list[RawEisSection]:
    """Single-element alias for embedder compatibility."""
    return [self.source]
```

Re-run the chunker tests to confirm nothing regressed: `cd backend && pytest tests/test_eis_chunker.py -x` — expect PASS.

- [ ] **Step 2: Also give EisChunk an embedder-compatible adapter for `build_breadcrumb`**

The shared embedder calls `build_breadcrumb(chunk)` from `rag/regulatory/breadcrumbs.py`. That function expects the regulatory-style chunk. We sidestep the coupling by pre-building the breadcrumb at call time in our ingest orchestrator — we will NOT call `embed_chunks` with the shared breadcrumb builder. Instead we define a local embedder entrypoint that uses `section.breadcrumb` directly. This is implemented in Task 8. No change needed here.

- [ ] **Step 3: Write the failing test**

Create `backend/tests/test_evaluation_store.py`:

```python
import json

import pytest

from rag.evaluation.chunker import EisChunk
from rag.evaluation.parser import RawEisSection
from rag.evaluation.store import (
    build_eis_metadata,
    init_evaluation_chunks_table,
    search_evaluation_chunks,
    upsert_evaluation_chunks,
)


def _make_eval_row(conn, filename="test.pdf", sha="abc"):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO evaluations (filename, sha256, size_bytes, blob) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (filename, sha, 10, b"dummy"),
        )
        return cur.fetchone()[0]


def _make_chunk(section_number="4.1", body="body text") -> EisChunk:
    section = RawEisSection(
        chapter="4",
        section_number=section_number,
        section_title="Water",
        breadcrumb=f"Chapter 4 > {section_number} Water",
        body=body, page_start=1, page_end=2,
    )
    return EisChunk(source=section, body=body, chunk_index=0, total_chunks_in_section=1,
                    token_count=2)


def test_init_table_creates_schema(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS evaluations ("
                    "id SERIAL PRIMARY KEY, filename TEXT, sha256 TEXT, "
                    "size_bytes INTEGER, blob BYTEA, uploaded_at TIMESTAMPTZ DEFAULT now())")
    init_evaluation_chunks_table(db_conn, embedding_dim=8)
    with db_conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.evaluation_chunks')")
        assert cur.fetchone()[0] == "evaluation_chunks"


def test_upsert_and_search_scoped_to_evaluation(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS evaluations ("
                    "id SERIAL PRIMARY KEY, filename TEXT, sha256 TEXT UNIQUE, "
                    "size_bytes INTEGER, blob BYTEA, uploaded_at TIMESTAMPTZ DEFAULT now())")
    init_evaluation_chunks_table(db_conn, embedding_dim=4)

    eid_a = _make_eval_row(db_conn, filename="a.pdf", sha="sha-a")
    eid_b = _make_eval_row(db_conn, filename="b.pdf", sha="sha-b")

    c = _make_chunk()
    meta = build_eis_metadata(
        c, breadcrumb=c.source.breadcrumb,
        evaluation_id=eid_a, filename="a.pdf", sha256="sha-a",
        chunk_label="a §4.1 [p.1-2] (1/1)",
    )
    rows = [(c, c.source.breadcrumb, [0.1, 0.2, 0.3, 0.4], meta)]
    written = upsert_evaluation_chunks(db_conn, rows, evaluation_id=eid_a)
    assert written == 1

    # Same label under a different evaluation is a SEPARATE row (scoped dedupe).
    c2 = _make_chunk(body="body text B")
    meta2 = build_eis_metadata(
        c2, breadcrumb=c2.source.breadcrumb,
        evaluation_id=eid_b, filename="b.pdf", sha256="sha-b",
        chunk_label="a §4.1 [p.1-2] (1/1)",
    )
    upsert_evaluation_chunks(db_conn, [(c2, c2.source.breadcrumb, [0.5, 0.5, 0.5, 0.5], meta2)],
                             evaluation_id=eid_b)

    results = search_evaluation_chunks(db_conn, [0.1, 0.2, 0.3, 0.4],
                                       evaluation_id=eid_a, top_k=5)
    assert len(results) == 1
    assert results[0]["metadata"]["evaluation_id"] == eid_a

    # Searching under B returns B only
    results_b = search_evaluation_chunks(db_conn, [0.5, 0.5, 0.5, 0.5],
                                         evaluation_id=eid_b, top_k=5)
    assert len(results_b) == 1
    assert results_b[0]["metadata"]["evaluation_id"] == eid_b


def test_cascade_delete_removes_chunks(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS evaluations ("
                    "id SERIAL PRIMARY KEY, filename TEXT, sha256 TEXT UNIQUE, "
                    "size_bytes INTEGER, blob BYTEA, uploaded_at TIMESTAMPTZ DEFAULT now())")
    init_evaluation_chunks_table(db_conn, embedding_dim=4)
    eid = _make_eval_row(db_conn, sha="sha-x")

    c = _make_chunk()
    meta = build_eis_metadata(
        c, breadcrumb=c.source.breadcrumb,
        evaluation_id=eid, filename="t.pdf", sha256="sha-x",
        chunk_label="L1",
    )
    upsert_evaluation_chunks(db_conn, [(c, c.source.breadcrumb, [0.0, 0.0, 0.0, 0.0], meta)],
                             evaluation_id=eid)

    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM evaluations WHERE id = %s", (eid,))
        cur.execute("SELECT COUNT(*) FROM evaluation_chunks WHERE evaluation_id = %s", (eid,))
        assert cur.fetchone()[0] == 0
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && pytest tests/test_evaluation_store.py -x`
Expected: FAIL with `ModuleNotFoundError: No module named 'rag.evaluation.store'`.

- [ ] **Step 5: Implement the store**

Create `backend/rag/evaluation/store.py`:

```python
"""pgvector storage + cosine search for EIS evaluation chunks.

Mirrors rag/regulatory/store.py in shape. Differences:
  * FK column is ``evaluation_id INTEGER REFERENCES evaluations(id)``
    (not UUID — evaluations.id is SERIAL).
  * Dedupe key is ``(evaluation_id, chunk_label)``.
  * Search is always scoped to a single evaluation.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import psycopg2
import psycopg2.extras

from rag.evaluation.chunker import EisChunk

logger = logging.getLogger("eia.rag.evaluation.store")

DEFAULT_TABLE = "evaluation_chunks"


def init_evaluation_chunks_table(
    conn: Any,
    embedding_dim: int,
    table_name: str = DEFAULT_TABLE,
) -> None:
    """Create the table + indexes if missing. Recreate on dim mismatch."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')

        cur.execute(
            """
            SELECT a.atttypmod FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            WHERE c.relname = %s AND a.attname = 'embedding'
            """,
            (table_name,),
        )
        row = cur.fetchone()
        if row is not None and row[0] != embedding_dim:
            logger.warning(
                "Vector dim mismatch on %s: column=%d provider=%d — recreating",
                table_name, row[0], embedding_dim,
            )
            cur.execute(f"DROP TABLE {table_name} CASCADE;")
            conn.commit()

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                evaluation_id INTEGER NOT NULL
                    REFERENCES evaluations(id) ON DELETE CASCADE,
                embedding vector({embedding_dim}),
                content TEXT NOT NULL,
                breadcrumb TEXT NOT NULL,
                chunk_label TEXT NOT NULL,
                metadata JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {table_name}_dedupe "
            f"ON {table_name} (evaluation_id, chunk_label);"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {table_name}_eval_id_idx "
            f"ON {table_name} (evaluation_id);"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {table_name}_metadata_gin "
            f"ON {table_name} USING GIN (metadata jsonb_path_ops);"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {table_name}_embedding_hnsw "
            f"ON {table_name} USING hnsw (embedding vector_cosine_ops) "
            f"WITH (m = 16, ef_construction = 64);"
        )
    conn.commit()
    logger.info("Initialized %s with vector(%d)", table_name, embedding_dim)


def build_eis_metadata(
    chunk: EisChunk,
    breadcrumb: str,
    *,
    evaluation_id: int,
    filename: str,
    sha256: str,
    chunk_label: str,
) -> dict:
    s = chunk.source
    return {
        "evaluation_id": evaluation_id,
        "filename": filename,
        "sha256": sha256,
        "chapter": s.chapter,
        "section_number": s.section_number,
        "section_title": s.section_title,
        "breadcrumb": breadcrumb,
        "chunk_label": chunk_label,
        "page_start": s.page_start,
        "page_end": s.page_end,
        "chunk_index": chunk.chunk_index,
        "total_chunks_in_section": chunk.total_chunks_in_section,
        "token_count": chunk.token_count,
        "has_table": chunk.has_table,
    }


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def upsert_evaluation_chunks(
    conn: Any,
    rows: list[tuple[EisChunk, str, list[float], dict]],
    *,
    evaluation_id: int,
    table_name: str = DEFAULT_TABLE,
) -> int:
    """Insert or replace chunks keyed on ``(evaluation_id, chunk_label)``."""
    if not rows:
        return 0
    payload = [
        (
            evaluation_id,
            _vector_literal(emb),
            chunk.body,
            breadcrumb,
            meta["chunk_label"],
            json.dumps(meta),
        )
        for chunk, breadcrumb, emb, meta in rows
    ]
    sql = f"""
        INSERT INTO {table_name}
            (evaluation_id, embedding, content, breadcrumb, chunk_label, metadata)
        VALUES (%s, %s::vector, %s, %s, %s, %s::jsonb)
        ON CONFLICT (evaluation_id, chunk_label)
        DO UPDATE SET
            embedding = EXCLUDED.embedding,
            content = EXCLUDED.content,
            breadcrumb = EXCLUDED.breadcrumb,
            metadata = EXCLUDED.metadata,
            created_at = NOW();
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, payload, page_size=50)
    conn.commit()
    logger.info("Upserted %d rows into %s for evaluation_id=%d",
                len(payload), table_name, evaluation_id)
    return len(payload)


def cascade_delete_chunks_for_evaluation(
    conn: Any, evaluation_id: int, table_name: str = DEFAULT_TABLE,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {table_name} WHERE evaluation_id = %s",
            (evaluation_id,),
        )
        count = cur.rowcount
    conn.commit()
    return count


def search_evaluation_chunks(
    conn: Any,
    query_embedding: list[float],
    *,
    evaluation_id: int,
    top_k: int = 5,
    table_name: str = DEFAULT_TABLE,
) -> list[dict]:
    sql = f"""
        SELECT
            id::text,
            evaluation_id,
            content,
            breadcrumb,
            chunk_label,
            metadata,
            1 - (embedding <=> %s::vector) AS similarity
        FROM {table_name}
        WHERE evaluation_id = %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """
    vec = _vector_literal(query_embedding)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (vec, evaluation_id, vec, top_k))
        return [dict(r) for r in cur.fetchall()]


def list_chunks_for_evaluation(
    conn: Any, evaluation_id: int, *, limit: int, offset: int,
    table_name: str = DEFAULT_TABLE,
) -> list[dict]:
    sql = f"""
        SELECT
            id::text,
            chunk_label,
            breadcrumb,
            content,
            metadata,
            (metadata->>'page_start')::int AS page_start,
            (metadata->>'page_end')::int AS page_end
        FROM {table_name}
        WHERE evaluation_id = %s
        ORDER BY
            COALESCE((metadata->>'chapter')::int, 0),
            metadata->>'section_number',
            (metadata->>'chunk_index')::int
        LIMIT %s OFFSET %s;
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (evaluation_id, limit, offset))
        return [dict(r) for r in cur.fetchall()]


def count_chunks_for_evaluation(
    conn: Any, evaluation_id: int, table_name: str = DEFAULT_TABLE,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {table_name} WHERE evaluation_id = %s",
            (evaluation_id,),
        )
        return cur.fetchone()[0]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_evaluation_store.py -x`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add backend/rag/evaluation/store.py backend/rag/evaluation/chunker.py backend/tests/test_evaluation_store.py
git commit -m "feat(eis-store): pgvector DDL, upsert, and scoped search"
```

---

## Task 7: `db/evaluations.py` repository module

**Files:**
- Create: `backend/db/evaluations.py`
- Create: `backend/tests/test_evaluations_repo.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_evaluations_repo.py`:

```python
import pytest

from db.evaluations import (
    init_evaluations_schema,
    insert_evaluation,
    get_evaluation_by_id,
    get_evaluation_bytes,
    get_evaluation_by_sha,
    list_evaluations,
    delete_evaluation,
    update_evaluation_status,
    update_evaluation_progress,
    reset_evaluation_for_reingest,
    mark_stuck_evaluations_failed,
)


def test_init_schema_is_idempotent(db_conn):
    init_evaluations_schema(db_conn)
    init_evaluations_schema(db_conn)
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
             WHERE table_schema='public' AND table_name='evaluations'
        """)
        cols = {r[0] for r in cur.fetchall()}
    for expected in {"id", "filename", "sha256", "size_bytes", "blob",
                     "uploaded_at", "status", "status_message",
                     "chunks_total", "chunks_embedded", "sections_count",
                     "embedding_dim", "started_at", "finished_at"}:
        assert expected in cols, f"missing column: {expected}"


def test_insert_get_and_dedupe(db_conn):
    init_evaluations_schema(db_conn)
    row = insert_evaluation(
        db_conn, filename="a.pdf", sha256="sha-1", size_bytes=10, blob=b"X",
    )
    assert row["status"] == "pending"
    again = insert_evaluation(
        db_conn, filename="a.pdf", sha256="sha-1", size_bytes=10, blob=b"X",
    )
    assert again["id"] == row["id"]  # dedupe returns existing

    fetched = get_evaluation_by_id(db_conn, row["id"])
    assert fetched["filename"] == "a.pdf"

    by_sha = get_evaluation_by_sha(db_conn, "sha-1")
    assert by_sha["id"] == row["id"]

    blob = get_evaluation_bytes(db_conn, row["id"])
    assert blob == b"X"


def test_status_and_progress_updates(db_conn):
    init_evaluations_schema(db_conn)
    row = insert_evaluation(db_conn, filename="p.pdf", sha256="sha-p",
                            size_bytes=5, blob=b"Y")
    update_evaluation_status(db_conn, row["id"], status="embedding",
                             chunks_total=10, sections_count=3, embedding_dim=8,
                             started_at_now=True)
    update_evaluation_progress(db_conn, row["id"], chunks_embedded=5)
    update_evaluation_status(db_conn, row["id"], status="ready", finished_at_now=True)
    final = get_evaluation_by_id(db_conn, row["id"])
    assert final["status"] == "ready"
    assert final["chunks_total"] == 10
    assert final["chunks_embedded"] == 5
    assert final["started_at"] is not None
    assert final["finished_at"] is not None


def test_reset_for_reingest(db_conn):
    init_evaluations_schema(db_conn)
    row = insert_evaluation(db_conn, filename="r.pdf", sha256="sha-r",
                            size_bytes=5, blob=b"Z")
    update_evaluation_status(db_conn, row["id"], status="failed",
                             status_message="boom", chunks_total=7,
                             chunks_embedded=3)
    reset_evaluation_for_reingest(db_conn, row["id"])
    reset = get_evaluation_by_id(db_conn, row["id"])
    assert reset["status"] == "pending"
    assert reset["status_message"] is None
    assert reset["chunks_total"] == 0
    assert reset["chunks_embedded"] == 0


def test_mark_stuck(db_conn):
    init_evaluations_schema(db_conn)
    r1 = insert_evaluation(db_conn, filename="s1.pdf", sha256="sha-s1",
                           size_bytes=5, blob=b"A")
    r2 = insert_evaluation(db_conn, filename="s2.pdf", sha256="sha-s2",
                           size_bytes=5, blob=b"B")
    update_evaluation_status(db_conn, r1["id"], status="embedding",
                             chunks_total=5)
    # r2 stays 'pending'

    swept = mark_stuck_evaluations_failed(db_conn)
    assert swept == 2
    r1_after = get_evaluation_by_id(db_conn, r1["id"])
    assert r1_after["status"] == "failed"
    assert "interrupted" in (r1_after["status_message"] or "").lower()


def test_delete_evaluation_returns_count(db_conn):
    init_evaluations_schema(db_conn)
    row = insert_evaluation(db_conn, filename="d.pdf", sha256="sha-d",
                            size_bytes=5, blob=b"C")
    assert delete_evaluation(db_conn, row["id"]) == 1
    assert delete_evaluation(db_conn, row["id"]) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_evaluations_repo.py -x`
Expected: FAIL with `ModuleNotFoundError: No module named 'db.evaluations'`.

- [ ] **Step 3: Implement the repository**

Create `backend/db/evaluations.py`:

```python
"""Repository for the evaluations table (EIS PDF uploads).

Schema is provisioned idempotently at startup via
``init_evaluations_schema`` — includes the legacy columns plus the new
status/progress columns added for the EIS ingest pipeline.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger("eia.db.evaluations")


_LIST_COLUMNS = """
    id, filename, sha256, size_bytes, uploaded_at,
    status, status_message, chunks_total, chunks_embedded,
    sections_count, embedding_dim, started_at, finished_at
"""


def init_evaluations_schema(conn: Any) -> None:
    """Create the table if missing and add any new columns idempotently."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                id SERIAL PRIMARY KEY,
                filename TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                blob BYTEA NOT NULL,
                uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        cur.execute("""
            ALTER TABLE evaluations
              ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending',
              ADD COLUMN IF NOT EXISTS status_message TEXT,
              ADD COLUMN IF NOT EXISTS chunks_total INTEGER NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS chunks_embedded INTEGER NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS sections_count INTEGER NOT NULL DEFAULT 0,
              ADD COLUMN IF NOT EXISTS embedding_dim INTEGER,
              ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
              ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS evaluations_sha256_idx
              ON evaluations (sha256)
        """)
    conn.commit()


def _row_to_dict(r) -> dict:
    d = dict(r)
    for k in ("uploaded_at", "started_at", "finished_at"):
        if d.get(k) is not None:
            d[k] = d[k].isoformat()
    return d


def insert_evaluation(
    conn: Any, *, filename: str, sha256: str, size_bytes: int, blob: bytes,
) -> dict:
    """Insert a new evaluation row or return the existing row on sha256 hit."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT {_LIST_COLUMNS}
            FROM evaluations WHERE sha256 = %s
            """,
            (sha256,),
        )
        existing = cur.fetchone()
        if existing:
            return _row_to_dict(existing)

        cur.execute(
            f"""
            INSERT INTO evaluations (filename, sha256, size_bytes, blob)
            VALUES (%s, %s, %s, %s)
            RETURNING {_LIST_COLUMNS}
            """,
            (filename, sha256, size_bytes, psycopg2.Binary(blob)),
        )
        row = cur.fetchone()
    conn.commit()
    return _row_to_dict(row)


def get_evaluation_by_id(conn: Any, eid: int) -> Optional[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_LIST_COLUMNS} FROM evaluations WHERE id = %s",
            (eid,),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_evaluation_by_sha(conn: Any, sha256: str) -> Optional[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_LIST_COLUMNS} FROM evaluations WHERE sha256 = %s",
            (sha256,),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_evaluation_bytes(conn: Any, eid: int) -> Optional[bytes]:
    with conn.cursor() as cur:
        cur.execute("SELECT blob FROM evaluations WHERE id = %s", (eid,))
        r = cur.fetchone()
    if r is None:
        return None
    b = r[0]
    return bytes(b) if b is not None else None


def list_evaluations(conn: Any) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_LIST_COLUMNS} FROM evaluations ORDER BY uploaded_at DESC"
        )
        return [_row_to_dict(r) for r in cur.fetchall()]


def delete_evaluation(conn: Any, eid: int) -> int:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM evaluations WHERE id = %s", (eid,))
        count = cur.rowcount
    conn.commit()
    return count


def update_evaluation_status(
    conn: Any,
    eid: int,
    *,
    status: str,
    status_message: Optional[str] = None,
    chunks_total: Optional[int] = None,
    sections_count: Optional[int] = None,
    embedding_dim: Optional[int] = None,
    started_at_now: bool = False,
    finished_at_now: bool = False,
    chunks_embedded: Optional[int] = None,
) -> None:
    sets = ["status = %s"]
    args: list[Any] = [status]
    if status_message is not None:
        sets.append("status_message = %s"); args.append(status_message)
    else:
        # Clear any prior message when transitioning to pending/embedding/ready
        if status in ("pending", "embedding", "ready"):
            sets.append("status_message = NULL")
    if chunks_total is not None:
        sets.append("chunks_total = %s"); args.append(chunks_total)
    if chunks_embedded is not None:
        sets.append("chunks_embedded = %s"); args.append(chunks_embedded)
    if sections_count is not None:
        sets.append("sections_count = %s"); args.append(sections_count)
    if embedding_dim is not None:
        sets.append("embedding_dim = %s"); args.append(embedding_dim)
    if started_at_now:
        sets.append("started_at = NOW()")
    if finished_at_now:
        sets.append("finished_at = NOW()")
    args.append(eid)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE evaluations SET {', '.join(sets)} WHERE id = %s",
            args,
        )
    conn.commit()


def update_evaluation_progress(conn: Any, eid: int, *, chunks_embedded: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE evaluations SET chunks_embedded = %s WHERE id = %s",
            (chunks_embedded, eid),
        )
    conn.commit()


def reset_evaluation_for_reingest(conn: Any, eid: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluations
               SET status = 'pending',
                   status_message = NULL,
                   chunks_total = 0,
                   chunks_embedded = 0,
                   sections_count = 0,
                   started_at = NULL,
                   finished_at = NULL
             WHERE id = %s
            """,
            (eid,),
        )
    conn.commit()


def mark_stuck_evaluations_failed(conn: Any) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluations
               SET status = 'failed',
                   status_message = 'interrupted by restart'
             WHERE status IN ('pending', 'embedding')
            """,
        )
        count = cur.rowcount
    conn.commit()
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_evaluations_repo.py -x`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/db/evaluations.py backend/tests/test_evaluations_repo.py
git commit -m "feat(db): add evaluations repository with status/progress helpers"
```

---

## Task 8: EIS ingest orchestrator

**Files:**
- Create: `backend/services/evaluation_ingest.py`
- Create: `backend/tests/test_evaluation_ingest.py`

We do not reuse `rag.regulatory.embedder.embed_chunks` because it builds breadcrumbs via the regulatory-specific `build_breadcrumb`. Instead we implement a tiny local async embed loop that uses the section's own breadcrumb.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_evaluation_ingest.py`:

```python
import pytest

from db.evaluations import (
    init_evaluations_schema,
    insert_evaluation,
    get_evaluation_by_id,
)
from rag.evaluation.store import (
    count_chunks_for_evaluation,
    init_evaluation_chunks_table,
)
from services.evaluation_ingest import ingest_evaluation_sync
from tests.fixtures.eis.build_sample import build_sample_eis_bytes


class _StubProvider:
    provider_name = "stub"

    def __init__(self, dim=8):
        self.dim = dim
        self.calls = []

    def embed(self, text):
        self.calls.append(text)
        h = abs(hash(text)) % 1000
        return [(h + i) / 1000.0 for i in range(self.dim)]


@pytest.fixture
def prepared_db(db_conn):
    init_evaluations_schema(db_conn)
    init_evaluation_chunks_table(db_conn, embedding_dim=8)
    return db_conn


def test_ingest_end_to_end_happy_path(prepared_db):
    conn = prepared_db
    blob = build_sample_eis_bytes()
    row = insert_evaluation(conn, filename="sample.pdf", sha256="sha-ok",
                            size_bytes=len(blob), blob=blob)
    provider = _StubProvider(dim=8)

    ingest_evaluation_sync(conn, evaluation_id=row["id"],
                           embedding_provider=provider)

    final = get_evaluation_by_id(conn, row["id"])
    assert final["status"] == "ready"
    assert final["chunks_total"] > 0
    assert final["chunks_embedded"] == final["chunks_total"]
    assert final["sections_count"] > 0

    n_chunks = count_chunks_for_evaluation(conn, row["id"])
    assert n_chunks == final["chunks_total"]


def test_ingest_marks_failed_on_empty_pdf(prepared_db):
    import pymupdf
    conn = prepared_db
    doc = pymupdf.open(); doc.new_page()
    blob = bytes(doc.write()); doc.close()
    row = insert_evaluation(conn, filename="empty.pdf", sha256="sha-empty",
                            size_bytes=len(blob), blob=blob)

    provider = _StubProvider()
    ingest_evaluation_sync(conn, evaluation_id=row["id"],
                           embedding_provider=provider)

    final = get_evaluation_by_id(conn, row["id"])
    assert final["status"] == "failed"
    assert final["status_message"] is not None


def test_ingest_is_idempotent(prepared_db):
    conn = prepared_db
    blob = build_sample_eis_bytes()
    row = insert_evaluation(conn, filename="idem.pdf", sha256="sha-idem",
                            size_bytes=len(blob), blob=blob)
    provider = _StubProvider()

    ingest_evaluation_sync(conn, evaluation_id=row["id"],
                           embedding_provider=provider)
    first_count = count_chunks_for_evaluation(conn, row["id"])
    assert first_count > 0

    # Re-run — upsert on (evaluation_id, chunk_label) should not duplicate
    ingest_evaluation_sync(conn, evaluation_id=row["id"],
                           embedding_provider=provider)
    assert count_chunks_for_evaluation(conn, row["id"]) == first_count
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_evaluation_ingest.py -x`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.evaluation_ingest'`.

- [ ] **Step 3: Implement the orchestrator**

Create `backend/services/evaluation_ingest.py`:

```python
"""Background ingestion for EIS evaluations: parse → chunk → embed → upsert.

Sibling of services/regulatory_ingest.py. Designed for FastAPI
BackgroundTasks. Opens no connections of its own — the caller must pass
a writable psycopg2 connection.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Callable, Optional

from db.evaluations import (
    get_evaluation_bytes,
    get_evaluation_by_id,
    update_evaluation_progress,
    update_evaluation_status,
)
from rag.embedder_core import detect_embedding_dimension
from rag.evaluation.chunker import EisChunk, chunk_eis_sections
from rag.evaluation.parser import parse_eis_pdf
from rag.evaluation.store import (
    build_eis_metadata,
    cascade_delete_chunks_for_evaluation,
    upsert_evaluation_chunks,
)
from rag.evaluation.chunker import make_chunk_label

logger = logging.getLogger("eia.services.evaluation_ingest")

_PROGRESS_MIN_INTERVAL_S = 1.0
_PROGRESS_MIN_DELTA = 5


async def _embed_eis_chunks(
    chunks: list[EisChunk],
    provider: Any,
    concurrency: int = 4,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> list[tuple[str, list[float]]]:
    """Embed each chunk using its section's breadcrumb.

    Returns ``(breadcrumb, vector)`` tuples in the input order.
    """
    sem = asyncio.Semaphore(concurrency)
    total = len(chunks)
    done = 0
    done_lock = asyncio.Lock()
    results: list[Optional[tuple[str, list[float]]]] = [None] * total

    async def _one(i: int, c: EisChunk) -> None:
        nonlocal done
        async with sem:
            text = f"{c.source.breadcrumb}\n\n{c.body}"
            vec = await asyncio.to_thread(provider.embed, text)
            results[i] = (c.source.breadcrumb, vec)
        if on_progress is not None:
            async with done_lock:
                done += 1
                on_progress(done, total)

    await asyncio.gather(*(_one(i, c) for i, c in enumerate(chunks)))
    return [r for r in results if r is not None]


def ingest_evaluation_sync(
    conn: Any,
    *,
    evaluation_id: int,
    embedding_provider: Any,
    correlation_id: Optional[str] = None,
) -> None:
    cid = correlation_id or uuid.uuid4().hex[:8]

    def log(msg, *args):
        logger.info(f"[eval:{cid}] " + msg, *args)
    def warn(msg, *args):
        logger.warning(f"[eval:{cid}] " + msg, *args)
    def err(msg, *args):
        logger.error(f"[eval:{cid}] " + msg, *args)

    try:
        log("ingest start: evaluation_id=%s", evaluation_id)
        update_evaluation_status(conn, evaluation_id, status="embedding",
                                 started_at_now=True)

        row = get_evaluation_by_id(conn, evaluation_id)
        if row is None:
            raise RuntimeError(f"evaluation row not found: {evaluation_id}")
        blob = get_evaluation_bytes(conn, evaluation_id)
        if blob is None:
            raise RuntimeError(f"evaluation bytes missing: {evaluation_id}")

        t0 = time.time()
        sections, parse_warnings = parse_eis_pdf(blob)
        log("parse done: %d sections, %d warnings in %.2fs",
            len(sections), len(parse_warnings), time.time() - t0)

        if not sections:
            warn("zero sections detected — marking failed")
            update_evaluation_status(
                conn, evaluation_id, status="failed",
                status_message=(
                    "No sections detected by EIS parser. "
                    "The PDF may have no numbered headings or be empty."
                ),
            )
            return

        t0 = time.time()
        chunks = chunk_eis_sections(sections)
        log("chunking done: %d chunks in %.2fs",
            len(chunks), time.time() - t0)

        if not chunks:
            warn("sections produced zero chunks — marking failed")
            update_evaluation_status(
                conn, evaluation_id, status="failed",
                status_message="Chunker produced zero chunks from a non-empty section list.",
            )
            return

        dim = detect_embedding_dimension(embedding_provider)
        update_evaluation_status(
            conn, evaluation_id, status="embedding",
            chunks_total=len(chunks), sections_count=len(sections),
            embedding_dim=dim,
        )

        last_write_t = [0.0]
        last_write_n = [0]

        def on_progress(done: int, total: int) -> None:
            now = time.time()
            if (done == total
                or now - last_write_t[0] >= _PROGRESS_MIN_INTERVAL_S
                or done - last_write_n[0] >= _PROGRESS_MIN_DELTA):
                update_evaluation_progress(conn, evaluation_id,
                                           chunks_embedded=done)
                last_write_t[0] = now
                last_write_n[0] = done
                log("embedding progress: %d/%d", done, total)

        t0 = time.time()
        embeddings = asyncio.run(
            _embed_eis_chunks(chunks, embedding_provider,
                              concurrency=4, on_progress=on_progress)
        )
        log("embedding done in %.2fs", time.time() - t0)

        # Build rows (label + metadata + vector) and upsert.
        filename = row["filename"]
        sha = row["sha256"]
        rows: list[tuple] = []
        for chunk, (breadcrumb, vec) in zip(chunks, embeddings):
            label = make_chunk_label(
                filename=filename, section=chunk.source,
                chunk_index=chunk.chunk_index,
                total=chunk.total_chunks_in_section,
            )
            meta = build_eis_metadata(
                chunk, breadcrumb=breadcrumb,
                evaluation_id=evaluation_id,
                filename=filename, sha256=sha, chunk_label=label,
            )
            rows.append((chunk, breadcrumb, vec, meta))

        # Idempotent re-embed: remove prior chunks first so nothing stale lingers.
        cascade_delete_chunks_for_evaluation(conn, evaluation_id)
        written = upsert_evaluation_chunks(conn, rows,
                                           evaluation_id=evaluation_id)
        log("upserted %d chunks", written)

        update_evaluation_status(
            conn, evaluation_id, status="ready",
            chunks_total=written, finished_at_now=True,
        )
        log("status → ready")

    except Exception as exc:
        err("ingest failed: %s", exc, exc_info=True)
        try:
            conn.rollback()
        except Exception:
            err("rollback raised", exc_info=True)
        try:
            update_evaluation_status(
                conn, evaluation_id, status="failed",
                status_message=f"{type(exc).__name__}: {exc}",
            )
        except Exception:
            err("could not write failure status", exc_info=True)
```

- [ ] **Step 4: Create `backend/rag/embedder_core.py` thin re-export**

The ingest module imports `detect_embedding_dimension` from `rag.embedder_core` so it doesn't transitively import the regulatory parser/chunker. Create `backend/rag/embedder_core.py`:

```python
"""Thin alias for detect_embedding_dimension so EIS ingest doesn't pull
in the regulatory parser chain."""
from __future__ import annotations

from rag.regulatory.embedder import detect_embedding_dimension  # noqa: F401
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_evaluation_ingest.py -x`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/services/evaluation_ingest.py backend/rag/embedder_core.py backend/tests/test_evaluation_ingest.py
git commit -m "feat(eis-ingest): orchestrator with throttled progress updates"
```

---

## Task 9: Wire lifespan + API endpoints

**Files:**
- Modify: `backend/main.py`
- Create: `backend/tests/test_evaluations_api.py`

- [ ] **Step 1: Write the failing API test**

Create `backend/tests/test_evaluations_api.py`:

```python
import time
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.eis.build_sample import build_sample_eis_bytes


@pytest.fixture
def client():
    """Build a fresh TestClient with a stub embedding provider.

    Must monkeypatch the embedding provider factory before main.py is
    imported — lifespan creates the provider eagerly. We import main
    inside the fixture and override app.state after startup.
    """
    import importlib, sys
    if "main" in sys.modules:
        del sys.modules["main"]
    # Install a stub before import so lifespan initialization is fast.
    import llm.provider_factory as pf

    class _Stub:
        provider_name = "stub"
        def embed(self, text):
            h = abs(hash(text)) % 1000
            return [(h + i) / 1000.0 for i in range(8)]
    pf_orig = pf.get_embedding_provider
    pf.get_embedding_provider = lambda: _Stub()
    try:
        main = importlib.import_module("main")
        with TestClient(main.app) as c:
            yield c
    finally:
        pf.get_embedding_provider = pf_orig


def _wait_ready(client, eid, timeout=15):
    for _ in range(timeout * 2):
        r = client.get(f"/api/evaluations/{eid}")
        assert r.status_code == 200
        if r.json()["status"] in ("ready", "failed"):
            return r.json()
        time.sleep(0.5)
    raise AssertionError("evaluation did not finish in time")


def test_upload_and_ingest_happy(client):
    pdf = build_sample_eis_bytes()
    r = client.post(
        "/api/evaluations",
        files={"file": ("sample.pdf", BytesIO(pdf), "application/pdf")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] in ("pending", "embedding", "ready")

    final = _wait_ready(client, body["id"])
    assert final["status"] == "ready", final
    assert final["chunks_total"] > 0

    chunks = client.get(f"/api/evaluations/{body['id']}/chunks").json()
    assert chunks["total"] == final["chunks_total"]
    assert len(chunks["chunks"]) > 0
    first = chunks["chunks"][0]
    assert "chunk_label" in first
    assert "breadcrumb" in first

    search = client.post(
        f"/api/evaluations/{body['id']}/search",
        json={"query": "water resources", "top_k": 3},
    ).json()
    assert len(search["results"]) > 0
    assert "similarity" in search["results"][0]


def test_reingest_endpoint(client):
    pdf = build_sample_eis_bytes()
    r = client.post("/api/evaluations",
                    files={"file": ("r.pdf", BytesIO(pdf), "application/pdf")})
    eid = r.json()["id"]
    _wait_ready(client, eid)

    rr = client.post(f"/api/evaluations/{eid}/reingest")
    assert rr.status_code == 202
    final = _wait_ready(client, eid)
    assert final["status"] == "ready"


def test_duplicate_upload_returns_existing(client):
    pdf = build_sample_eis_bytes()
    r1 = client.post("/api/evaluations",
                     files={"file": ("d.pdf", BytesIO(pdf), "application/pdf")})
    r2 = client.post("/api/evaluations",
                     files={"file": ("d.pdf", BytesIO(pdf), "application/pdf")})
    assert r1.json()["id"] == r2.json()["id"]


def test_delete_cascade(client):
    pdf = build_sample_eis_bytes()
    r = client.post("/api/evaluations",
                    files={"file": ("del.pdf", BytesIO(pdf), "application/pdf")})
    eid = r.json()["id"]
    _wait_ready(client, eid)

    d = client.delete(f"/api/evaluations/{eid}")
    assert d.status_code == 204
    c = client.get(f"/api/evaluations/{eid}")
    assert c.status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_evaluations_api.py -x`
Expected: FAIL — endpoints don't exist, TestClient lifespan errors, etc.

- [ ] **Step 3: Modify `backend/main.py` — imports and lifespan**

Add to the imports near the top (after existing imports):

```python
from db.evaluations import (
    init_evaluations_schema,
    insert_evaluation,
    get_evaluation_by_id,
    get_evaluation_by_sha,
    list_evaluations,
    delete_evaluation,
    update_evaluation_status,
    reset_evaluation_for_reingest,
    mark_stuck_evaluations_failed,
)
from rag.evaluation.store import (
    init_evaluation_chunks_table,
    list_chunks_for_evaluation,
    count_chunks_for_evaluation,
    search_evaluation_chunks,
)
from services.evaluation_ingest import ingest_evaluation_sync
```

Replace the existing lifespan evaluations init block (roughly lines 112-130) with:

```python
    # --- evaluations table + evaluation_chunks table + sweep ----------
    try:
        _conn3 = _get_connection()
        init_evaluations_schema(_conn3)
        init_evaluation_chunks_table(_conn3, embedding_dim=dim)
        swept = mark_stuck_evaluations_failed(_conn3)
        if swept:
            print(f"[LIFESPAN] swept {swept} stuck evaluation rows",
                  flush=True, file=sys.stdout)
        _conn3.close()
        print(f"[LIFESPAN] evaluations + evaluation_chunks ready (dim={dim})",
              flush=True, file=sys.stdout)
    except Exception as exc:
        print(f"[LIFESPAN] evaluations init failed: {exc}",
              flush=True, file=sys.stdout)
```

- [ ] **Step 4: Replace existing evaluations endpoints with repo-backed ones**

Replace the existing evaluations block (roughly lines 550-638, starting at the `# --- Evaluations (EIS document uploads) ---` comment) with:

```python
# --- Evaluations (EIS document uploads) ------------------------------------

def _run_evaluation_ingest_background(evaluation_id: int, correlation_id: str) -> None:
    try:
        conn = _get_connection()
    except Exception:
        _sources_logger.exception(
            "[eval:%s] failed to open DB connection", correlation_id,
        )
        return
    try:
        ingest_evaluation_sync(
            conn,
            evaluation_id=evaluation_id,
            embedding_provider=app.state.embedding_provider,
            correlation_id=correlation_id,
        )
    except Exception:
        _sources_logger.exception(
            "[eval:%s] ingest raised in background task", correlation_id,
        )
    finally:
        try:
            conn.close()
        except Exception:
            _sources_logger.exception(
                "[eval:%s] conn.close() raised", correlation_id,
            )


@app.get("/api/evaluations")
def list_evaluations_endpoint():
    conn = _get_connection()
    try:
        return {"documents": list_evaluations(conn)}
    finally:
        conn.close()


@app.get("/api/evaluations/{eid}")
def get_evaluation_endpoint(eid: int):
    conn = _get_connection()
    try:
        row = get_evaluation_by_id(conn, eid)
        if row is None:
            raise HTTPException(status_code=404, detail="evaluation not found")
        return row
    finally:
        conn.close()


@app.post("/api/evaluations", status_code=201)
async def upload_evaluation(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    if file.content_type not in ("application/pdf", "application/x-pdf", "binary/octet-stream"):
        raise HTTPException(status_code=400, detail="file must be a PDF")

    buf = bytearray()
    _CHUNK = 1 << 20
    while True:
        piece = await file.read(_CHUNK)
        if not piece:
            break
        buf.extend(piece)
        if len(buf) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"file too large (>{_MAX_UPLOAD_BYTES} bytes)",
            )
    blob = bytes(buf)
    if len(blob) == 0:
        raise HTTPException(status_code=400, detail="empty file")
    if not blob.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="not a valid PDF")

    sha = hashlib.sha256(blob).hexdigest()
    fname = file.filename or "upload.pdf"

    conn = _get_connection()
    try:
        row = insert_evaluation(
            conn, filename=fname, sha256=sha,
            size_bytes=len(blob), blob=blob,
        )
    finally:
        conn.close()

    if row["status"] == "pending":
        cid = _new_correlation_id()
        _sources_logger.info(
            "[eval:%s] queueing background ingest for id=%s", cid, row["id"],
        )
        background_tasks.add_task(_run_evaluation_ingest_background,
                                  row["id"], cid)
    return row


@app.post("/api/evaluations/{eid}/reingest", status_code=202)
def reingest_evaluation(eid: int, background_tasks: BackgroundTasks):
    conn = _get_connection()
    try:
        row = get_evaluation_by_id(conn, eid)
        if row is None:
            raise HTTPException(status_code=404, detail="evaluation not found")
        if row["status"] == "embedding":
            raise HTTPException(status_code=409, detail="ingest already running")
        reset_evaluation_for_reingest(conn, eid)
    finally:
        conn.close()
    cid = _new_correlation_id()
    background_tasks.add_task(_run_evaluation_ingest_background, eid, cid)
    return {"id": eid, "status": "pending", "correlation_id": cid}


@app.get("/api/evaluations/{eid}/chunks")
def get_evaluation_chunks(eid: int, page: int = 1, per_page: int = 25):
    per_page = max(1, min(per_page, 200))
    page = max(1, page)
    offset = (page - 1) * per_page
    conn = _get_connection()
    try:
        if get_evaluation_by_id(conn, eid) is None:
            raise HTTPException(status_code=404, detail="evaluation not found")
        total = count_chunks_for_evaluation(conn, eid)
        chunks = list_chunks_for_evaluation(conn, eid,
                                            limit=per_page, offset=offset)
    finally:
        conn.close()
    total_pages = (total + per_page - 1) // per_page if total else 0
    return {
        "evaluation_id": eid,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "chunks": chunks,
    }


class EvaluationSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=50)


@app.post("/api/evaluations/{eid}/search")
def search_evaluation(eid: int, req: EvaluationSearchRequest):
    conn = _get_connection()
    try:
        if get_evaluation_by_id(conn, eid) is None:
            raise HTTPException(status_code=404, detail="evaluation not found")
        vec = app.state.embedding_provider.embed(req.query)
        results = search_evaluation_chunks(
            conn, vec, evaluation_id=eid, top_k=req.top_k,
        )
    finally:
        conn.close()
    return {"evaluation_id": eid, "query": req.query, "results": results}


@app.delete("/api/evaluations/{eid}", status_code=204)
def delete_evaluation_endpoint(eid: int):
    conn = _get_connection()
    try:
        if delete_evaluation(conn, eid) == 0:
            raise HTTPException(status_code=404, detail="evaluation not found")
    finally:
        conn.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_evaluations_api.py -x`
Expected: PASS (4 tests).

- [ ] **Step 6: Run full backend suite to catch regressions**

Run: `cd backend && pytest -x`
Expected: all passing. If `test_detect_parser.py` or older tests touching `evaluations` fail because of schema changes, investigate — the new schema is additive so they should still pass.

- [ ] **Step 7: Commit**

```bash
git add backend/main.py backend/tests/test_evaluations_api.py
git commit -m "feat(api): EIS evaluation ingest endpoints + reingest + chunks + search"
```

---

## Task 10: Startup sweep test

**Files:**
- Create: `backend/tests/test_evaluation_startup_sweep.py`

- [ ] **Step 1: Write the test**

Create `backend/tests/test_evaluation_startup_sweep.py`:

```python
from db.evaluations import (
    init_evaluations_schema,
    insert_evaluation,
    update_evaluation_status,
    get_evaluation_by_id,
    mark_stuck_evaluations_failed,
)


def test_sweep_marks_pending_and_embedding_as_failed(db_conn):
    init_evaluations_schema(db_conn)
    r_pending = insert_evaluation(db_conn, filename="p.pdf", sha256="sp",
                                  size_bytes=5, blob=b"A")
    r_embedding = insert_evaluation(db_conn, filename="e.pdf", sha256="se",
                                    size_bytes=5, blob=b"B")
    update_evaluation_status(db_conn, r_embedding["id"], status="embedding")
    r_ready = insert_evaluation(db_conn, filename="r.pdf", sha256="sr",
                                size_bytes=5, blob=b"C")
    update_evaluation_status(db_conn, r_ready["id"], status="ready")

    n = mark_stuck_evaluations_failed(db_conn)
    assert n == 2

    assert get_evaluation_by_id(db_conn, r_pending["id"])["status"] == "failed"
    assert get_evaluation_by_id(db_conn, r_embedding["id"])["status"] == "failed"
    assert get_evaluation_by_id(db_conn, r_ready["id"])["status"] == "ready"
```

- [ ] **Step 2: Run and verify pass**

Run: `cd backend && pytest tests/test_evaluation_startup_sweep.py -x`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_evaluation_startup_sweep.py
git commit -m "test(eval): verify startup sweep marks stuck rows failed"
```

---

## Task 11: Frontend — EvaluationsView polling, status, RETRY

**Files:**
- Modify: `frontend/src/components/EvaluationsView.jsx`
- Create: `frontend/src/components/EvaluationsView.test.jsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/EvaluationsView.test.jsx`:

```jsx
import { render, screen, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import EvaluationsView from './EvaluationsView.jsx'

function jsonRes(body, ok = true, status = 200) {
  return Promise.resolve({
    ok, status, json: () => Promise.resolve(body),
  })
}

describe('EvaluationsView', () => {
  let originalFetch
  beforeEach(() => {
    originalFetch = global.fetch
    vi.useFakeTimers()
  })
  afterEach(() => {
    global.fetch = originalFetch
    vi.useRealTimers()
  })

  it('renders status pill and progress for an embedding row', async () => {
    global.fetch = vi.fn(() => jsonRes({
      documents: [{
        id: 1, filename: 'x.pdf', sha256: 'abc', size_bytes: 2048,
        uploaded_at: new Date().toISOString(),
        status: 'embedding', chunks_total: 10, chunks_embedded: 4,
        status_message: null,
      }],
    }))
    render(<EvaluationsView onBack={() => {}} onOpenChunks={() => {}} />)
    await waitFor(() => expect(screen.getByText(/EMBEDDING/i)).toBeTruthy())
    expect(screen.getByText(/4\s*\/\s*10/)).toBeTruthy()
  })

  it('shows RETRY only on failed rows', async () => {
    global.fetch = vi.fn(() => jsonRes({
      documents: [
        { id: 1, filename: 'a.pdf', status: 'ready', chunks_total: 3,
          chunks_embedded: 3, size_bytes: 10, uploaded_at: new Date().toISOString() },
        { id: 2, filename: 'b.pdf', status: 'failed', chunks_total: 0,
          chunks_embedded: 0, size_bytes: 10, uploaded_at: new Date().toISOString(),
          status_message: 'bad pdf' },
      ],
    }))
    render(<EvaluationsView onBack={() => {}} onOpenChunks={() => {}} />)
    await waitFor(() => expect(screen.getAllByRole('row').length).toBeGreaterThan(1))
    const retryBtns = screen.getAllByText(/RETRY/i)
    expect(retryBtns).toHaveLength(1)
  })

  it('stops polling on unmount', async () => {
    const fetchSpy = vi.fn(() => jsonRes({
      documents: [{ id: 1, filename: 'a.pdf', status: 'embedding',
        chunks_total: 5, chunks_embedded: 1, size_bytes: 10,
        uploaded_at: new Date().toISOString() }],
    }))
    global.fetch = fetchSpy
    const { unmount } = render(<EvaluationsView onBack={() => {}} onOpenChunks={() => {}} />)
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled())
    const before = fetchSpy.mock.calls.length
    unmount()
    act(() => { vi.advanceTimersByTime(10000) })
    expect(fetchSpy.mock.calls.length).toBe(before)
  })
})
```

- [ ] **Step 2: Run the failing tests**

Run: `cd frontend && npm test -- --run EvaluationsView.test`
Expected: FAIL (component doesn't accept `onOpenChunks`, no RETRY button, no polling).

- [ ] **Step 3: Rewrite `frontend/src/components/EvaluationsView.jsx`**

Replace the file contents with:

```jsx
import { useEffect, useRef, useState } from 'react'

const apiBase = import.meta.env.VITE_API_URL ?? ''
const POLL_INTERVAL_MS = 2000
const TERMINAL = new Set(['ready', 'failed'])

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function StatusPill({ doc }) {
  const s = doc.status || 'pending'
  const base = { ...styles.pill }
  if (s === 'ready') base.borderColor = 'var(--green-primary)'
  else if (s === 'failed') { base.borderColor = 'var(--red-alert)'; base.color = 'var(--red-alert)' }
  else if (s === 'embedding') base.borderColor = 'var(--amber, #b4a347)'
  else base.borderColor = 'var(--text-muted)'

  let label = s.toUpperCase()
  if (s === 'embedding' && doc.chunks_total > 0) {
    label = `EMBEDDING ${doc.chunks_embedded || 0}/${doc.chunks_total}`
  }
  return (
    <span style={base} title={doc.status_message || ''}>{label}</span>
  )
}

function ProgressBar({ doc }) {
  if (doc.status !== 'embedding' || !doc.chunks_total) return null
  const pct = Math.min(100, Math.round((doc.chunks_embedded / doc.chunks_total) * 100))
  return (
    <div style={styles.progressOuter}>
      <div style={{ ...styles.progressInner, width: `${pct}%` }} />
    </div>
  )
}

export default function EvaluationsView({ onBack, onOpenChunks }) {
  const [docs, setDocs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef(null)
  const mountedRef = useRef(true)
  const timerRef = useRef(null)

  const pollOnce = async () => {
    try {
      const res = await fetch(`${apiBase}/api/evaluations`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      if (!mountedRef.current) return
      setDocs(data.documents || [])
      setError(null)
    } catch (e) {
      if (mountedRef.current) setError(e.message)
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }

  useEffect(() => {
    mountedRef.current = true
    pollOnce()
    return () => { mountedRef.current = false; if (timerRef.current) clearInterval(timerRef.current) }
  }, [])

  useEffect(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    const hasNonTerminal = docs.some(d => !TERMINAL.has(d.status || 'pending'))
    if (hasNonTerminal) {
      timerRef.current = setInterval(pollOnce, POLL_INTERVAL_MS)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [docs])

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true); setError(null)
    try {
      const form = new FormData(); form.append('file', file)
      const res = await fetch(`${apiBase}/api/evaluations`, { method: 'POST', body: form })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      const doc = await res.json()
      setDocs(prev => {
        const existing = prev.find(d => d.id === doc.id)
        if (existing) return prev.map(d => d.id === doc.id ? doc : d)
        return [doc, ...prev]
      })
    } catch (e) { setError(e.message) }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = '' }
  }

  const handleDelete = async (id) => {
    if (!confirm('Delete this evaluation and all its chunks?')) return
    try {
      const res = await fetch(`${apiBase}/api/evaluations/${id}`, { method: 'DELETE' })
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`)
      setDocs(prev => prev.filter(d => d.id !== id))
    } catch (e) { setError(e.message) }
  }

  const handleRetry = async (id) => {
    try {
      const res = await fetch(`${apiBase}/api/evaluations/${id}/reingest`, { method: 'POST' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      pollOnce()
    } catch (e) { setError(e.message) }
  }

  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button style={styles.backBtn} onClick={onBack}>&larr; BACK</button>
        <span style={styles.pageTitle}>EVALUATIONS</span>
        <span style={styles.docCount}>
          {!loading && !error && `${docs.length} documents`}
        </span>
      </div>

      <div style={styles.body}>
        <div style={styles.uploadZone}>
          <input
            ref={fileRef}
            type="file" accept=".pdf"
            onChange={handleUpload}
            style={{ display: 'none' }}
          />
          <button
            style={styles.uploadBtn}
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? 'UPLOADING...' : 'UPLOAD EIS PDF'}
          </button>
          <span style={styles.uploadHint}>PDF files up to 25 MB</span>
        </div>

        {error && <div style={styles.error}>Error: {error}</div>}
        {loading && <div style={styles.muted}>Loading...</div>}
        {!loading && docs.length === 0 && (
          <div style={styles.muted}>No evaluation documents uploaded yet.</div>
        )}

        {!loading && docs.length > 0 && (
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>FILENAME</th>
                <th style={styles.th}>SIZE</th>
                <th style={styles.th}>STATUS</th>
                <th style={styles.th}>UPLOADED</th>
                <th style={styles.th}></th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} style={styles.tr}>
                  <td style={styles.td}>
                    <button
                      style={styles.linkBtn}
                      onClick={() => onOpenChunks && onOpenChunks(d.id, d.filename)}
                      disabled={d.status !== 'ready'}
                      title={d.status !== 'ready' ? 'Chunks available once ingest is ready' : 'View chunks'}
                    >
                      {d.filename}
                    </button>
                  </td>
                  <td style={styles.td}>{formatBytes(d.size_bytes)}</td>
                  <td style={styles.td}>
                    <StatusPill doc={d} />
                    <ProgressBar doc={d} />
                  </td>
                  <td style={styles.td}>
                    {new Date(d.uploaded_at).toLocaleDateString()}
                  </td>
                  <td style={styles.td}>
                    {d.status === 'failed' && (
                      <button style={styles.retryBtn} onClick={() => handleRetry(d.id)}>
                        RETRY
                      </button>
                    )}
                    <button style={styles.deleteBtn} onClick={() => handleDelete(d.id)}>
                      DELETE
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

const styles = {
  container: { height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  topBar: {
    display: 'flex', alignItems: 'center', gap: '16px', padding: '12px 24px',
    borderBottom: '1px solid var(--border)', background: 'var(--bg-secondary)', flexShrink: 0,
  },
  backBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '11px', letterSpacing: '1px',
    color: 'var(--text-secondary)', background: 'transparent',
    border: '1px solid var(--border)', borderRadius: '4px', padding: '6px 12px', cursor: 'pointer',
  },
  pageTitle: {
    fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600,
    color: 'var(--green-primary)', letterSpacing: '3px',
  },
  docCount: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' },
  body: { flex: 1, padding: '24px', overflowY: 'auto' },
  uploadZone: { display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '24px' },
  uploadBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '11px', letterSpacing: '1px',
    color: 'var(--green-primary)', background: 'transparent',
    border: '1px solid var(--green-primary)', borderRadius: '4px', padding: '8px 16px', cursor: 'pointer',
  },
  uploadHint: { fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' },
  error: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--red-alert)', padding: '8px 0' },
  muted: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic', padding: '8px 0' },
  table: { width: '100%', borderCollapse: 'collapse' },
  th: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '1px',
    color: 'var(--text-muted)', textAlign: 'left', padding: '8px 12px',
    borderBottom: '1px solid var(--border)',
  },
  tr: { borderBottom: '1px solid var(--border)' },
  td: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)', padding: '10px 12px' },
  pill: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '1px',
    color: 'var(--green-primary)', background: 'transparent',
    border: '1px solid var(--green-primary)', borderRadius: '3px', padding: '2px 6px', display: 'inline-block',
  },
  progressOuter: {
    marginTop: '4px', width: '100px', height: '3px', background: 'var(--border)',
    borderRadius: '2px', overflow: 'hidden',
  },
  progressInner: { height: '100%', background: 'var(--green-primary)' },
  linkBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--green-primary)',
    background: 'transparent', border: 'none', padding: 0, cursor: 'pointer', textDecoration: 'underline',
  },
  retryBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '1px',
    color: 'var(--green-primary)', background: 'transparent',
    border: '1px solid var(--green-primary)', borderRadius: '3px', padding: '3px 8px',
    cursor: 'pointer', marginRight: '8px',
  },
  deleteBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '1px',
    color: 'var(--red-alert)', background: 'transparent',
    border: '1px solid var(--red-alert)', borderRadius: '3px', padding: '3px 8px', cursor: 'pointer',
  },
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- --run EvaluationsView.test`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EvaluationsView.jsx frontend/src/components/EvaluationsView.test.jsx
git commit -m "feat(frontend): evaluations status polling, progress bar, RETRY button"
```

---

## Task 12: Frontend — EvaluationChunksView inspector

**Files:**
- Create: `frontend/src/components/EvaluationChunksView.jsx`
- Create: `frontend/src/components/EvaluationChunksView.test.jsx`
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/EvaluationChunksView.test.jsx`:

```jsx
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import EvaluationChunksView from './EvaluationChunksView.jsx'

function jsonRes(body) {
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })
}

describe('EvaluationChunksView', () => {
  let orig
  beforeEach(() => { orig = global.fetch })
  afterEach(() => { global.fetch = orig })

  it('renders chunk labels and breadcrumbs', async () => {
    global.fetch = vi.fn(() => jsonRes({
      evaluation_id: 1, page: 1, per_page: 25, total: 2, total_pages: 1,
      chunks: [
        { id: 'a', chunk_label: 'sample §1.1 [p.1] (1/1)',
          breadcrumb: 'Chapter 1 > 1.1 Overview', content: 'body',
          page_start: 1, page_end: 1, metadata: {} },
        { id: 'b', chunk_label: 'sample §4.1 [p.2-3] (1/1)',
          breadcrumb: 'Chapter 4 > 4.1 Water', content: 'body2',
          page_start: 2, page_end: 3, metadata: {} },
      ],
    }))
    render(<EvaluationChunksView
      evaluationId={1} filename="sample.pdf" onBack={() => {}} />)
    await waitFor(() => expect(screen.getByText(/1\.1 Overview/)).toBeTruthy())
    expect(screen.getByText(/sample §1\.1/)).toBeTruthy()
    expect(screen.getByText(/sample §4\.1/)).toBeTruthy()
  })

  it('calls onBack when back button clicked', async () => {
    global.fetch = vi.fn(() => jsonRes({
      evaluation_id: 1, page: 1, per_page: 25, total: 0, total_pages: 0, chunks: [],
    }))
    const onBack = vi.fn()
    render(<EvaluationChunksView evaluationId={1} filename="x.pdf" onBack={onBack} />)
    await waitFor(() => expect(screen.getByText(/NO CHUNKS/i)).toBeTruthy())
    fireEvent.click(screen.getByText(/BACK/))
    expect(onBack).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run failing tests**

Run: `cd frontend && npm test -- --run EvaluationChunksView.test`
Expected: FAIL (component doesn't exist).

- [ ] **Step 3: Create `frontend/src/components/EvaluationChunksView.jsx`**

```jsx
import { useEffect, useRef, useState } from 'react'

const apiBase = import.meta.env.VITE_API_URL ?? ''

export default function EvaluationChunksView({ evaluationId, filename, onBack }) {
  const [chunks, setChunks] = useState([])
  const [page, setPage] = useState(1)
  const [perPage] = useState(25)
  const [totalPages, setTotalPages] = useState(0)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [expanded, setExpanded] = useState(() => new Set())
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    setLoading(true); setError(null)
    fetch(`${apiBase}/api/evaluations/${evaluationId}/chunks?page=${page}&per_page=${perPage}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(d => {
        if (!mountedRef.current) return
        setChunks(d.chunks || []); setTotalPages(d.total_pages || 0); setTotal(d.total || 0)
      })
      .catch(e => { if (mountedRef.current) setError(e.message) })
      .finally(() => { if (mountedRef.current) setLoading(false) })
  }, [evaluationId, page, perPage])

  const toggle = (id) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  return (
    <div style={styles.container}>
      <div style={styles.topBar}>
        <button style={styles.backBtn} onClick={onBack}>&larr; BACK</button>
        <span style={styles.pageTitle}>CHUNKS: {filename}</span>
        <span style={styles.count}>{!loading && !error && `${total} chunks`}</span>
      </div>
      <div style={styles.body}>
        {error && <div style={styles.error}>Error: {error}</div>}
        {loading && <div style={styles.muted}>Loading...</div>}
        {!loading && chunks.length === 0 && <div style={styles.muted}>NO CHUNKS</div>}
        {!loading && chunks.length > 0 && (
          <>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>LABEL</th>
                  <th style={styles.th}>BREADCRUMB</th>
                  <th style={styles.th}>PAGES</th>
                  <th style={styles.th}>CONTENT</th>
                </tr>
              </thead>
              <tbody>
                {chunks.map(c => {
                  const isOpen = expanded.has(c.id)
                  const body = isOpen ? c.content : (c.content || '').slice(0, 160) + (c.content?.length > 160 ? '…' : '')
                  return (
                    <tr key={c.id} style={styles.tr}>
                      <td style={styles.tdMono}>{c.chunk_label}</td>
                      <td style={styles.td}>{c.breadcrumb}</td>
                      <td style={styles.tdMono}>{c.page_start === c.page_end ? c.page_start : `${c.page_start}-${c.page_end}`}</td>
                      <td style={styles.td}>
                        <button style={styles.expandBtn} onClick={() => toggle(c.id)}>
                          {isOpen ? '▼' : '▶'}
                        </button>
                        <span style={{ whiteSpace: 'pre-wrap' }}>{body}</span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {totalPages > 1 && (
              <div style={styles.pager}>
                <button style={styles.pagerBtn} disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>PREV</button>
                <span style={styles.pageLabel}>PAGE {page} / {totalPages}</span>
                <button style={styles.pagerBtn} disabled={page >= totalPages} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>NEXT</button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

const styles = {
  container: { height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  topBar: {
    display: 'flex', alignItems: 'center', gap: '16px', padding: '12px 24px',
    borderBottom: '1px solid var(--border)', background: 'var(--bg-secondary)', flexShrink: 0,
  },
  backBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '11px', letterSpacing: '1px',
    color: 'var(--text-secondary)', background: 'transparent',
    border: '1px solid var(--border)', borderRadius: '4px', padding: '6px 12px', cursor: 'pointer',
  },
  pageTitle: {
    fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600,
    color: 'var(--green-primary)', letterSpacing: '2px',
  },
  count: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' },
  body: { flex: 1, padding: '24px', overflowY: 'auto' },
  error: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--red-alert)', padding: '8px 0' },
  muted: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)', fontStyle: 'italic', padding: '8px 0' },
  table: { width: '100%', borderCollapse: 'collapse' },
  th: {
    fontFamily: 'var(--font-mono)', fontSize: '9px', letterSpacing: '1px',
    color: 'var(--text-muted)', textAlign: 'left', padding: '8px 12px',
    borderBottom: '1px solid var(--border)',
  },
  tr: { borderBottom: '1px solid var(--border)', verticalAlign: 'top' },
  td: { fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-secondary)', padding: '8px 12px' },
  tdMono: { fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--green-primary)', padding: '8px 12px' },
  expandBtn: {
    background: 'transparent', border: 'none', color: 'var(--green-primary)',
    cursor: 'pointer', marginRight: '6px', fontFamily: 'var(--font-mono)',
  },
  pager: {
    display: 'flex', alignItems: 'center', gap: '12px', marginTop: '16px',
    justifyContent: 'center',
  },
  pagerBtn: {
    fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '1px',
    color: 'var(--green-primary)', background: 'transparent',
    border: '1px solid var(--green-primary)', borderRadius: '3px',
    padding: '4px 10px', cursor: 'pointer',
  },
  pageLabel: { fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-muted)' },
}
```

- [ ] **Step 4: Verify ChunksView tests pass**

Run: `cd frontend && npm test -- --run EvaluationChunksView.test`
Expected: PASS.

- [ ] **Step 5: Modify `frontend/src/App.jsx`**

Add import for the new view and thread the route. Replace the existing import block (lines 1-9) with:

```jsx
import { useState } from 'react'
import ProjectForm from './components/ProjectForm.jsx'
import AgentPipeline from './components/AgentPipeline.jsx'
import ResultsPanel from './components/ResultsPanel.jsx'
import BrainScanner from './components/BrainScanner.jsx'
import DatabaseView from './components/DatabaseView.jsx'
import EvaluationsView from './components/EvaluationsView.jsx'
import EvaluationChunksView from './components/EvaluationChunksView.jsx'
import useModelSelections from './hooks/useModelSelections.js'
import { runEcfrIngestCommand } from './lib/ecfrIngestCommand.js'
```

Inside the `App` function, add a new state just after the existing `view` state (around line 27):

```jsx
  const [selectedEvalId, setSelectedEvalId] = useState(null)
  const [selectedEvalFilename, setSelectedEvalFilename] = useState(null)
```

Replace the existing view-switch block (lines 111-115) with:

```jsx
      {view === 'db' ? (
        <DatabaseView onBack={() => setView('main')} />
      ) : view === 'evaluations' ? (
        <EvaluationsView
          onBack={() => setView('main')}
          onOpenChunks={(eid, filename) => {
            setSelectedEvalId(eid)
            setSelectedEvalFilename(filename)
            setView('evaluation-chunks')
          }}
        />
      ) : view === 'evaluation-chunks' ? (
        <EvaluationChunksView
          evaluationId={selectedEvalId}
          filename={selectedEvalFilename}
          onBack={() => setView('evaluations')}
        />
      ) : (
```

- [ ] **Step 6: Verify frontend suite passes**

Run: `cd frontend && npm test -- --run`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/EvaluationChunksView.jsx frontend/src/components/EvaluationChunksView.test.jsx frontend/src/App.jsx
git commit -m "feat(frontend): EvaluationChunksView inspector + app routing"
```

---

## Task 13: Documentation

**Files:**
- Create: `docs/eval-pipeline.md`
- Modify: `README.md`

- [ ] **Step 1: Write `docs/eval-pipeline.md`**

```markdown
# EIS Evaluation Ingestion

The Evaluations page accepts EIS (Environmental Impact Statement) PDF
uploads. Uploaded PDFs are automatically parsed, chunked, embedded, and
stored in the `evaluation_chunks` table for retrieval.

## Upload flow

```
User uploads PDF → POST /api/evaluations
    → evaluations row (status='pending')
    → BackgroundTask → parse → chunk → embed → upsert
    → evaluations row (status='ready')
```

The Evaluations page polls `/api/evaluations` every 2 seconds while any
row is `pending` or `embedding` and shows:
- Status pill (`PENDING`, `EMBEDDING n/N`, `READY`, `FAILED`)
- Progress bar during `embedding`
- `RETRY` button on `failed` rows
- Filename becomes a clickable link to the chunks inspector when `ready`

## Chunk labels

Every chunk gets a human-readable label:

```
{filename_stem} §{section_number} [p.{page_start}-{page_end}] ({index+1}/{total})
```

Example: `ch-4-environmental-resources §4.2.3 [p.142-143] (2/5)`

Labels are unique per `(evaluation_id, chunk_label)` and back the
upsert's dedupe key.

## API reference

| Method | Path |
|---|---|
| `POST` | `/api/evaluations` — upload PDF, auto-ingest (sha256 dedupe returns existing row) |
| `GET` | `/api/evaluations` — list with status/progress |
| `GET` | `/api/evaluations/{id}` — single row (used by UI polling) |
| `POST` | `/api/evaluations/{id}/reingest` — clears chunks, re-runs pipeline |
| `GET` | `/api/evaluations/{id}/chunks?page=&per_page=` — paginated chunks inspector data |
| `POST` | `/api/evaluations/{id}/search` — scoped similarity search |
| `DELETE` | `/api/evaluations/{id}` — cascades to chunks via FK |

### Search example

```bash
curl -X POST http://localhost:8000/api/evaluations/42/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "groundwater aquifer recharge", "top_k": 5}'
```

## Status lifecycle

- `pending` — row exists, background task queued
- `embedding` — parse complete, embedding chunks (see `chunks_embedded` / `chunks_total`)
- `ready` — all chunks upserted
- `failed` — parse/chunk/embed error; `status_message` has details

On server restart, any row stuck in `pending` or `embedding` is swept to
`failed` with `status_message = 'interrupted by restart'`. Use the
`RETRY` button or `POST /api/evaluations/{id}/reingest` to restart.

## Common failure modes

- **`No sections detected by EIS parser`** — the PDF lacks numbered
  headings the parser recognises (e.g., `1.1`, `4.2.3`). Low-quality
  scans or purely narrative PDFs can trigger this. Currently not
  supported — consider a different document.
- **`Vector dim mismatch`** — logged at startup if the embedding
  provider changed dims between runs. The table is recreated and
  chunks must be re-ingested (use the RETRY button on each row).
- **Status stuck on `embedding` with `0/0`** — the parse step
  produced zero sections. Row will transition to `failed` momentarily
  with a message.

## Database schema

`evaluations` (extended on startup):
- `status TEXT DEFAULT 'pending'`
- `status_message TEXT`
- `chunks_total INTEGER`, `chunks_embedded INTEGER`
- `sections_count INTEGER`, `embedding_dim INTEGER`
- `started_at`, `finished_at TIMESTAMPTZ`

`evaluation_chunks`:
- `id UUID`, `evaluation_id INTEGER REFERENCES evaluations(id) ON DELETE CASCADE`
- `embedding vector(<dim>)`, `content TEXT`, `breadcrumb TEXT`, `chunk_label TEXT`
- `metadata JSONB` — includes `chapter`, `section_number`, `page_start/end`, `token_count`, `has_table`
- Indexes: HNSW on `embedding` (cosine), GIN on `metadata`, UNIQUE `(evaluation_id, chunk_label)`
```

- [ ] **Step 2: Update `README.md`**

Find the "Regulatory Source Ingestion" section and add this subsection below it:

```markdown
### EIS Evaluation Ingestion

EIS documents uploaded on the Evaluations page are automatically parsed,
chunked, embedded, and stored in the `evaluation_chunks` table for
scoped retrieval.

- Upload via the Evaluations page, or `POST /api/evaluations`
- Query via `POST /api/evaluations/{id}/search`

See [`docs/eval-pipeline.md`](docs/eval-pipeline.md) for the operator guide.
```

- [ ] **Step 3: Commit**

```bash
git add docs/eval-pipeline.md README.md
git commit -m "docs: add EIS evaluation pipeline operator guide"
```

---

## Task 14: Final verification

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && pytest -x`
Expected: all tests PASS.

- [ ] **Step 2: Run the full frontend test suite**

Run: `cd frontend && npm test -- --run`
Expected: all tests PASS.

- [ ] **Step 3: Manual smoke test (optional, requires real DB + provider)**

In one terminal: `cd backend && uvicorn main:app --reload --port 8000`
In another: `cd frontend && npm run dev`

- Open http://localhost:5173
- Click EVALUATIONS
- Upload one of the FEIS sample PDFs from `~/Downloads/`
- Watch the row transition `PENDING` → `EMBEDDING n/N` → `READY`
- Click the filename to open the chunks inspector; verify labels look right
- Curl: `curl -X POST localhost:8000/api/evaluations/{id}/search -H 'Content-Type: application/json' -d '{"query":"water resources","top_k":3}'`

- [ ] **Step 4: Create PR**

```bash
git push -u origin feat/ecfr-phase-1
gh pr create --title "feat: EIS evaluation ingestion pipeline"
```

---

## Self-Review Notes

- **Spec coverage:** All design sections map to tasks:
  - Architecture/modules → Tasks 3–8
  - DB schema (evaluations ALTER + evaluation_chunks DDL) → Task 6, 7, 9
  - API surface → Task 9
  - Frontend (status pill, progress bar, RETRY, chunks inspector, routing) → Tasks 11, 12
  - Testing (6 backend test files + 2 frontend) → Tasks 2–12
  - Documentation → Task 13
  - Startup sweep → Task 9 (wired) + Task 10 (tested)

- **Placeholder scan:** No TODOs, no "TBD", no hand-wavy steps. Every code step shows actual code.

- **Type consistency:** `EisChunk`, `RawEisSection`, `init_evaluation_chunks_table`, `upsert_evaluation_chunks`, `search_evaluation_chunks`, `chunk_label`, `build_eis_metadata`, `ingest_evaluation_sync` used consistently across all tasks. `detect_embedding_dimension` imported via `rag.embedder_core` alias in Task 8 to avoid transitive pymupdf import of the regulatory parser chain.

- **Known risk:** Task 8 Step 3 uses `hash(text)` in the stub provider — Python hash randomization means the same text gives different vectors across processes. Because the stub is only used within a single test process this is fine; search results match on vector equality within that process.
