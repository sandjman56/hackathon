# PA Code Chapter 105 Parser + Regulatory Corpus Expansion

**Date:** 2026-04-12
**Status:** Draft
**Scope:** New state-level PDF parser for 25 PA Code Chapter 105; future corpus reference list

---

## Problem

The regulatory screening agent only has NEPA (40 CFR 1500-1508) in its corpus. Every screening output is a NEPA process step (EA, FONSI, ROD). The environmental data agent already pulls wetland, species, floodplain, farmland, and EJ data — but the screening agent can't surface state-level permits because no state regulations exist in the vector store.

For the Pittsburgh solar farm demo (50 MW, 400 acres, wetlands, tributaries), the agent should be surfacing PA DEP Chapter 105 waterway/wetland permits alongside the federal NEPA requirements.

## Design

### Architecture: Parser-per-source-format

Each PDF source format gets its own parser module under `rag/regulatory/`. Parsers are categorized by jurisdiction:

```
rag/regulatory/
  parser.py              # existing — federal CFR (NEPA scanned reprint)
  parser_pa_code.py      # new — PA Code (browser-printed from pacodeandbulletin.gov)
  chunker.py             # shared — no changes needed
  embedder.py            # shared — no changes needed
  store.py               # shared — extend DocumentType enum
  breadcrumbs.py         # shared — add state_code breadcrumb format
  xref.py                # shared — add PA Code citation patterns
  normalize.py           # existing — federal-specific, not needed for PA Code
```

The chunker, embedder, and store are source-agnostic. Only the parser and downstream metadata (breadcrumbs, xref patterns) vary by source format. If a future state PDF has a different format (e.g., NJ Admin Code), that's a new parser module — not a modification to the PA one.

### DocumentType Extension

Add to the existing `DocumentType` enum in `parser.py`:

```python
class DocumentType(str, Enum):
    CFR_REGULATION = "cfr_regulation"
    STATUTE = "statute"
    EXECUTIVE_ORDER = "executive_order"
    STATE_CODE = "state_code"          # new
```

### Source PDF Characteristics

**File:** `Pennsylvania Code.pdf` (140 pages, 1.2 MB)
**Origin:** Chrome "Print to PDF" from pacodeandbulletin.gov
**Content:** 25 PA Code Chapter 105 — Dam Safety and Waterway Management
**Subchapters:** A (General Provisions) through M (Statements of Policy)

Key formatting traits vs. the existing federal parser:

| Feature | Federal (NEPA) | State (PA Code) |
|---------|---------------|-----------------|
| Text quality | Corrupted Unicode (U+FFFD) | Clean Unicode |
| Section headers | `§1501.3 Title text.` | `§ 105.14. Title text.` (note space after §) |
| Part/Subchapter | `PART 1501—TITLE` | `Subchapter B. DAMS AND RESERVOIRS` |
| Group headers | None | `GENERAL PROVISIONS`, `PERMIT APPLICATIONS` |
| Page header | `25 § 105.1 ... Pt. I` | `4/12/26, 11:28 AM ... Pennsylvania Code` |
| Page footer | `105-4` | `about:blank ... N/140` |
| Metadata blocks | None | Authority, Source, Cross References, Notes of Decisions |
| Definitions | Italic term + em-dash | Same pattern |
| [Reserved] sections | None | Many (e.g., `§ 105.72. [Reserved].`) |
| Appendices | None | Appendices A-O (all [Reserved]) |
| Hyperlinks | None | Section numbers hyperlinked in TOC |

### PA Code Parser Design (`parser_pa_code.py`)

#### Output

Same `RawSection` dataclass as the federal parser, with these field mappings:

| RawSection field | PA Code mapping |
|-----------------|----------------|
| `document_type` | `DocumentType.STATE_CODE` |
| `section` | `"105.14"` |
| `title` | `"Review of applications"` |
| `body` | Regulatory text only (no Authority/Source/Cross Refs/Notes) |
| `citation` | `"25 Pa. Code § 105.14"` |
| `pages` | PDF page numbers |
| `part` | Subchapter letter: `"A"`, `"B"`, etc. |
| `part_title` | `"GENERAL PROVISIONS"`, `"DAMS AND RESERVOIRS"`, etc. |
| `parent_statute` | `None` (this is a regulation, not a statute) |
| `statute_title` | `None` |
| `effective_date` | Extracted from Source block if present |

New metadata fields stored on RawSection (or passed through to chunk metadata):

| Field | Source | Example |
|-------|--------|---------|
| `authority` | Authority block text | `"Dam Safety and Encroachments Act (32 P.S. §§ 693.1-693.27)..."` |
| `source_history` | Source block text | `"adopted September 10, 1971..."` |
| `cross_references` | Cross References block text | `"25 Pa. Code § 105.15..."` |
| `notes_of_decisions` | Notes of Decisions block text | Case law summaries |
| `jurisdiction` | Hardcoded | `"Pennsylvania"` |
| `agency` | Hardcoded | `"PA DEP"` |
| `subchapter` | Subchapter letter | `"B"` |
| `section_group` | Group header text | `"PERMIT APPLICATIONS"` |

#### Header Detection Regexes

```python
# Section header: "§ 105.14. Review of applications."
# Also handles: "§ 105.13a. Complete applications." and "§ 105.46a."
_RE_PA_SECTION = re.compile(
    r"^\s*§\s*(?P<section>\d+\.\d+[a-z]?)\.?\s+(?P<title>.+?)\.?\s*$"
)

# Subchapter header: "Subchapter B. DAMS AND RESERVOIRS"
# Sometimes multi-line: "Subchapter E. CHANNEL CHANGES AND\nDREDGING FOR..."
_RE_SUBCHAPTER = re.compile(
    r"^\s*Subchapter\s+(?P<letter>[A-Z])\.?\s+(?P<title>[A-Z][A-Z\s,\-]+)"
)

# Section group headers (all caps, centered): "GENERAL PROVISIONS", "PERMITS"
_RE_GROUP_HEADER = re.compile(
    r"^(?P<title>[A-Z][A-Z,\s\-—]+[A-Z])$"
)

# Reserved section: "§ 105.72. [Reserved]."
_RE_RESERVED = re.compile(
    r"^\s*§\s*\d+\.\d+[a-z]?\.?\s+\[Reserved\]\.?\s*$"
)

# Definition entry: "Italic term—definition text" (em-dash separator)
_RE_DEFINITION = re.compile(
    r"^\s*(?P<term>[A-Z][a-z][\w\s]+)\s*[—\-]\s*(?P<body>.+)"
)
```

#### Noise Stripping

**Browser artifacts to remove:**
- Lines matching `^\d+/\d+/\d+,\s+\d+:\d+\s+[AP]M` (timestamp header)
- Lines matching `^Pennsylvania Code$` (right header)
- Lines matching `^about:blank$` (left footer)
- Lines matching `^\d+/\d+$` (page number footer)
- Lines matching `^Close Window$` (link artifact on page 1)

**Content to skip entirely:**
- TOC pages (pages 1-4, detected by presence of linked section numbers without body text)
- `[Reserved]` sections — skip, do not emit a RawSection
- Appendices A-O (all [Reserved]) — skip
- Empty sections that contain only Authority/Source blocks and no regulatory text

#### Metadata Block Detection

After each section's body text, detect and extract these blocks as metadata (not body):

```python
# Authority block starts with centered bold "Authority"
# Source block starts with centered bold "Source"
# Cross References block starts with centered bold "Cross References"
# Notes of Decisions block starts with bold "Notes of Decisions"
```

Each block continues until the next section header, subchapter header, or another metadata block keyword. Store as string metadata on the RawSection — do not include in body text that gets embedded.

#### Parse Flow

```
1. Extract all text from PDF (pymupdf, page by page)
2. Strip browser noise (timestamps, about:blank, page numbers)
3. Detect TOC pages -> skip
4. Walk pages, detecting:
   a. Subchapter boundaries -> update current subchapter context
   b. Section group headers -> update current group context
   c. Section headers (§ NNN.NN. Title.) -> start new section
   d. [Reserved] sections -> skip
   e. Metadata blocks (Authority/Source/Cross Refs/Notes) -> attach to current section
   f. Definition entries in § 105.1 -> emit as individual sections with is_definition=True
   g. Body text -> append to current section
5. Emit completed RawSection for each non-reserved section
```

### Breadcrumb Format for State Code

Add a `_state_code_breadcrumb` function to `breadcrumbs.py`:

```
Title 25 — Environmental Protection > Chapter 105 — Dam Safety and Waterway Management
> Subchapter A — General Provisions > § 105.14 — Review of applications
```

For definitions in § 105.1:
```
Title 25 — Environmental Protection > Chapter 105 — Dam Safety and Waterway Management
> § 105.1 — Definitions [DEFINITION]
```

### Cross-Reference Patterns for State Code

Add PA Code citation patterns to `xref.py`:

```python
# PA Code: "25 Pa. Code § 105.14" / "§ 105.14(b)" / "§§ 105.13(d) and 105.14(b)"
_RE_PA_CODE_REF = re.compile(
    r"(?:25\s*Pa\.?\s*Code\s*)?\u00a7{1,2}\s*(\d+\.\d+[a-z]?)(?:\([a-z0-9]+\))*"
)

# PA Statutes: "32 P.S. §§ 693.1-693.27" / "35 P.S. § 691.1"
_RE_PA_STATUTE_REF = re.compile(
    r"(\d+)\s*P\.?\s*S\.?\s*\u00a7{1,2}\s*([\d.]+)"
)
```

### Chunker Compatibility

The existing chunker works on `RawSection` objects and is document-type-agnostic. No changes needed except:

- Definition detection: currently checks `part == "1508"` — needs to also handle `section == "105.1"` for PA Code definitions
- Sibling merging: currently merges within the same `part` — for state code, merge within the same `subchapter` (the `part` field maps to subchapter letter)

### Store Metadata

The metadata JSONB stored per chunk will include:

```json
{
  "citation": "25 Pa. Code § 105.14",
  "section": "105.14",
  "part": "A",
  "document_type": "state_code",
  "jurisdiction": "Pennsylvania",
  "agency": "PA DEP",
  "subchapter": "A",
  "subchapter_title": "General Provisions",
  "section_group": "PERMIT APPLICATIONS",
  "is_current": true,
  "is_definition": false,
  "is_merged_siblings": false,
  "token_count": 542,
  "page_numbers": [30, 31, 32],
  "cross_references": ["25 Pa. Code § 105.15", "25 Pa. Code § 105.18a"],
  "authority": "Dam Safety and Encroachments Act (32 P.S. §§ 693.1-693.27)...",
  "effective_date": "1971-09-11",
  "source_id": "<uuid of regulatory_sources row>"
}
```

### Ingestion Integration

The existing `services/regulatory_ingest.py` calls `parse() -> chunk() -> embed() -> upsert()`. To support the PA Code parser:

1. Add a `parser_type` field to `regulatory_sources` table (or detect automatically from PDF content)
2. Auto-detection heuristic: if first page contains "Pennsylvania Code", use `parser_pa_code`; if it contains "PART 1500" or "40 CFR", use existing `parser`
3. The ingest service selects the appropriate parser, then feeds `RawSection` objects into the shared chunker/embedder/store pipeline

---

## Future Regulatory Sources (Reference List)

These are not designed — just names and locations for future lookup. Grouped by jurisdiction.

### Federal

| Priority | Document | Citation | What it covers | Maps to env data signal |
|----------|----------|----------|---------------|------------------------|
| F1 | Clean Water Act §404 Regulations | 33 CFR Parts 320-330 | Federal wetland/waterway permits (Army Corps) | NWI wetlands |
| F2 | Endangered Species Act §7 Regulations | 50 CFR Part 402 | Federal consultation for T&E species | IPaC species |
| F3 | National Historic Preservation Act §106 Regulations | 36 CFR Part 800 | Cultural resource review process | (no current API signal) |
| F4 | Farmland Protection Policy Act Regulations | 7 CFR Part 658 | Prime farmland conversion review | SSURGO farmland |
| F5 | EO 12898 (Environmental Justice) | Executive Order 12898 | EJ analysis requirements | EJScreen data |
| F6 | Clean Air Act — Prevention of Significant Deterioration | 40 CFR Part 52 | Air quality permits for major sources | (no current API signal) |

### Pennsylvania State

| Priority | Document | Citation | What it covers | Maps to env data signal |
|----------|----------|----------|---------------|------------------------|
| S1 | PA Code Chapter 105 | 25 Pa. Code Ch. 105 | Waterway/wetland permits (this spec) | NWI wetlands |
| S2 | PA Code Chapter 102 | 25 Pa. Code Ch. 102 | Erosion & sediment control, NPDES stormwater | SSURGO farmland |
| S3 | PA Code Chapter 93 | 25 Pa. Code Ch. 93 | Water quality standards, stream classifications | NWI wetlands |
| S4 | PA Game/Fish & Boat Code | 58 Pa. Code Ch. 133 / 30 Pa.C.S. Ch. 75 | State-listed T&E species | IPaC species (state analog) |
| S5 | PA Act 43 | 3 P.S. §§ 901-915 | Agricultural security areas, farmland preservation | SSURGO farmland |
| S6 | PA History Code | 37 Pa.C.S. Ch. 5 | State historic/cultural resource review | (no current API signal) |
| S7 | PA DEP Solar Siting Guidance | Technical Guidance 310-2100-003 | Solar-specific environmental review | All signals |

### Local (Future)

| Priority | Document | What it covers |
|----------|----------|---------------|
| L1 | Allegheny County zoning ordinances | Local land use for Pittsburgh-area projects |
| L2 | Municipal stormwater ordinances | MS4 requirements for specific municipalities |

---

## Test Plan

- [ ] Unit test: parser extracts correct section count from PA Code PDF (expected: ~80-90 non-reserved sections)
- [ ] Unit test: parser strips browser noise (timestamps, about:blank, page numbers)
- [ ] Unit test: parser skips [Reserved] sections and all-reserved appendices
- [ ] Unit test: definitions in § 105.1 parsed as individual sections with is_definition=True
- [ ] Unit test: metadata blocks (Authority, Source, Cross References) attached to sections, not in body
- [ ] Unit test: breadcrumb format matches spec (Title 25 > Chapter 105 > Subchapter > Section)
- [ ] Unit test: xref extracts PA Code citations (25 Pa. Code § NNN.NN) and PA statute citations (NN P.S. § NNN)
- [ ] Integration test: full parse -> chunk -> embed pipeline produces chunks in regulatory_chunks table
- [ ] Integration test: regulatory screening agent retrieves PA Code chunks alongside NEPA chunks for a wetland query
- [ ] E2E test: Pittsburgh solar farm pipeline run surfaces at least one PA DEP permit in regulations output
