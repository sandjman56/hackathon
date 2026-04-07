"""Section -> chunk conversion with token-aware splitting and merging.

Implements the chunking strategy from the project spec:

* One chunk = one CFR section, by default.
* Sections > ``MAX_TOKENS`` (1500) are split on paragraph-label boundaries
  (``(a)``, ``(b)``, ``(c)``, ...). Each split slice gets a ``subsection``
  metadata field describing its range.
* Sections < ``MIN_TOKENS`` (200) are merged with the next sibling section
  in the same Part. Merged chunks record both citations.
* Definitions in Part 1508 are *never* merged or split — one definition
  per chunk, even if short.
* Overlap (~12%) is applied only between slices of a *split* section,
  never across section boundaries (which would muddy citations).
* Token counting uses ``tiktoken`` with ``cl100k_base``, the encoding used
  by most modern embedding models.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import tiktoken

from .parser import DocumentType, RawSection

logger = logging.getLogger("eia.rag.regulatory.chunker")


# Tunable thresholds — token counts via cl100k_base.
MIN_TOKENS = 200       # below this, merge with next sibling (same Part)
MAX_TOKENS = 1500      # above this, split on paragraph boundaries
TARGET_TOKENS = 700    # aim for ~500-800 per chunk after splitting
OVERLAP_TOKENS = 90    # ~12% overlap between slices of a split section


@dataclass
class Chunk:
    """A chunk-ready slice of one or more RawSections."""

    sources: list[RawSection]   # 1 normally, 2+ when sibling-merged
    body: str
    subsection: Optional[str] = None  # e.g. "(a)-(c)" when split
    chunk_index: int = 0
    total_chunks_in_section: int = 1
    has_table: bool = False
    is_definition: bool = False
    is_merged_siblings: bool = False
    token_count: int = 0
    extra: dict = field(default_factory=dict)  # for parser-set flags


# --- token utilities -----------------------------------------------------

_ENCODER = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Return the cl100k_base token count for ``text``."""
    return len(_ENCODER.encode(text))


def _decode(tokens: list[int]) -> str:
    return _ENCODER.decode(tokens)


# --- helpers --------------------------------------------------------------

# Matches a paragraph label like " (a) ", " (b) ", but only when it begins a
# clause (preceded by sentence end / whitespace / start of body, not inside
# another paren). The look-behind is intentional: section bodies cite
# "(§1501.7)" inline and we must NOT split there. The leading ``^`` branch
# lets a section that opens directly with ``(a)`` still get a label.
_PARA_LABEL_RE = re.compile(r"(?:^|(?<=[\.\:\;\s]))(\([a-z]\))\s")
# Detects whether a chunk contains a markdown-style table line
_TABLE_HINT_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


def _is_definition_section(raw: RawSection) -> bool:
    return raw.document_type == DocumentType.CFR_REGULATION and raw.part == "1508"


def _split_into_paragraphs(body: str) -> list[tuple[str, str]]:
    """Slice a long section body on (a)/(b)/(c) labels.

    Returns:
        A list of ``(label, text)`` tuples preserving document order.
        ``label`` is the matched paragraph marker (e.g. ``"(a)"``); the
        opening pre-label fragment, if any, is returned with label ``""``.
    """
    matches = list(_PARA_LABEL_RE.finditer(body))
    if not matches:
        return [("", body.strip())]

    pieces: list[tuple[str, str]] = []
    first_start = matches[0].start()
    if first_start > 0:
        prefix = body[:first_start].strip()
        if prefix:
            pieces.append(("", prefix))

    for i, m in enumerate(matches):
        label = m.group(1)  # e.g. "(a)"
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        pieces.append((label, body[start:end].strip()))
    return pieces


# --- core chunking --------------------------------------------------------

def chunk_section(raw: RawSection) -> list[Chunk]:
    """Convert one RawSection into one or more Chunks.

    Definitions (Part 1508) are emitted as a single chunk regardless of
    size — they are retrieved as glossary entries and must not be merged
    or split. All other sections follow the merge/split rules at chunk
    time, except that *merging* across siblings is handled in
    :func:`chunk_sections` because it needs cross-section context.
    """
    body = raw.body.strip()
    is_def = _is_definition_section(raw)
    tokens = count_tokens(body)
    has_table = bool(_TABLE_HINT_RE.search(body))

    if is_def:
        return [
            Chunk(
                sources=[raw],
                body=body,
                subsection=None,
                chunk_index=0,
                total_chunks_in_section=1,
                is_definition=True,
                has_table=has_table,
                token_count=tokens,
            )
        ]

    if tokens <= MAX_TOKENS:
        return [
            Chunk(
                sources=[raw],
                body=body,
                subsection=None,
                chunk_index=0,
                total_chunks_in_section=1,
                has_table=has_table,
                token_count=tokens,
            )
        ]

    # ---- split path ----
    pieces = _split_into_paragraphs(body)
    if len(pieces) <= 1:
        # No paragraph labels — fall back to a token-window split. Last
        # resort: pure tokens. We never want a chunk above MAX_TOKENS.
        return _token_window_split(raw, body, has_table)

    return _greedy_pack_paragraphs(raw, pieces, has_table)


def _greedy_pack_paragraphs(
    raw: RawSection, pieces: list[tuple[str, str]], has_table: bool
) -> list[Chunk]:
    """Pack labeled paragraphs into chunks of ~TARGET_TOKENS, with overlap."""
    chunks: list[Chunk] = []
    current_pieces: list[tuple[str, str]] = []
    current_tokens = 0

    def flush_current() -> None:
        nonlocal current_pieces, current_tokens
        if not current_pieces:
            return
        text = " ".join(p[1] for p in current_pieces).strip()
        labels = [p[0] for p in current_pieces if p[0]]
        sub = _format_subsection(labels)
        chunks.append(
            Chunk(
                sources=[raw],
                body=text,
                subsection=sub,
                chunk_index=len(chunks),
                total_chunks_in_section=0,  # filled in below
                has_table=has_table,
                token_count=count_tokens(text),
            )
        )
        current_pieces = []
        current_tokens = 0

    for label, text in pieces:
        piece_tokens = count_tokens(text)
        # If a single piece is itself > MAX_TOKENS, split it on tokens.
        if piece_tokens > MAX_TOKENS:
            flush_current()
            chunks.extend(_token_window_split(raw, text, has_table))
            continue
        if current_tokens + piece_tokens > TARGET_TOKENS and current_pieces:
            flush_current()
        current_pieces.append((label, text))
        current_tokens += piece_tokens

    flush_current()

    # Apply overlap between adjacent split chunks (ONLY within this section).
    chunks = _apply_overlap(chunks)

    # Set total_chunks_in_section now that we know the count.
    for i, c in enumerate(chunks):
        c.chunk_index = i
        c.total_chunks_in_section = len(chunks)
    return chunks


def _format_subsection(labels: list[str]) -> Optional[str]:
    if not labels:
        return None
    if len(labels) == 1:
        return labels[0]
    return f"{labels[0]}-{labels[-1]}"


def _apply_overlap(chunks: list[Chunk]) -> list[Chunk]:
    """Prepend the tail of chunk N to the head of chunk N+1."""
    if len(chunks) < 2:
        return chunks
    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        prev_tokens = _ENCODER.encode(prev.body)
        if len(prev_tokens) <= OVERLAP_TOKENS:
            continue
        overlap_text = _decode(prev_tokens[-OVERLAP_TOKENS:])
        chunks[i].body = overlap_text + " " + chunks[i].body
        chunks[i].token_count = count_tokens(chunks[i].body)
    return chunks


def _token_window_split(
    raw: RawSection, body: str, has_table: bool
) -> list[Chunk]:
    """Last-resort fixed-token split for sections without paragraph labels."""
    tokens = _ENCODER.encode(body)
    chunks: list[Chunk] = []
    step = TARGET_TOKENS - OVERLAP_TOKENS
    i = 0
    while i < len(tokens):
        window = tokens[i : i + TARGET_TOKENS]
        text = _decode(window).strip()
        chunks.append(
            Chunk(
                sources=[raw],
                body=text,
                subsection=f"window-{len(chunks)}",
                chunk_index=len(chunks),
                total_chunks_in_section=0,
                has_table=has_table,
                token_count=len(window),
            )
        )
        i += step
    for i, c in enumerate(chunks):
        c.chunk_index = i
        c.total_chunks_in_section = len(chunks)
    return chunks


# --- top-level orchestration ---------------------------------------------

def chunk_sections(raws: list[RawSection]) -> list[Chunk]:
    """Convert an ordered list of RawSections into chunks with sibling merging.

    The merging step runs *after* per-section chunking and only fires when
    a small section sits next to another small section in the *same Part*
    (or, for statutes, the same parent statute). Definitions are never
    merged.
    """
    # First pass — chunk each section individually.
    per_section: list[list[Chunk]] = [chunk_section(r) for r in raws]

    # Second pass — sibling-merge runts. We only merge a section if it
    # produced exactly one chunk and that chunk is below MIN_TOKENS.
    merged: list[Chunk] = []
    i = 0
    while i < len(per_section):
        chunks = per_section[i]
        if (
            len(chunks) == 1
            and not chunks[0].is_definition
            and chunks[0].token_count < MIN_TOKENS
            and i + 1 < len(per_section)
            and len(per_section[i + 1]) == 1
            and not per_section[i + 1][0].is_definition
            and _are_siblings(chunks[0].sources[0], per_section[i + 1][0].sources[0])
        ):
            # Try merging with the next sibling. If still under MAX_TOKENS,
            # keep merging additional siblings (rare but possible).
            buffer_chunk = chunks[0]
            j = i + 1
            while (
                j < len(per_section)
                and len(per_section[j]) == 1
                and not per_section[j][0].is_definition
                and _are_siblings(buffer_chunk.sources[0], per_section[j][0].sources[0])
                and buffer_chunk.token_count + per_section[j][0].token_count <= MAX_TOKENS
                and (
                    buffer_chunk.token_count < MIN_TOKENS
                    or per_section[j][0].token_count < MIN_TOKENS
                )
            ):
                buffer_chunk = _merge_two_chunks(buffer_chunk, per_section[j][0])
                j += 1
            merged.append(buffer_chunk)
            i = j
            continue
        merged.extend(chunks)
        i += 1

    # Third pass — backward-merge any remaining orphan runts. This fires
    # when a section is the *last* in its Part (no next sibling to absorb
    # it forward), e.g. §1500.6 or §1505.3 in this PDF.
    final: list[Chunk] = []
    for chunk in merged:
        if (
            final
            and chunk.token_count < MIN_TOKENS
            and not chunk.is_definition
            and len(chunk.sources) == 1
            and final[-1].sources
            and _are_siblings(final[-1].sources[-1], chunk.sources[0])
            and final[-1].token_count + chunk.token_count <= MAX_TOKENS
            and not final[-1].is_definition
        ):
            final[-1] = _merge_two_chunks(final[-1], chunk)
            continue
        final.append(chunk)
    return final


def _are_siblings(a: RawSection, b: RawSection) -> bool:
    """True if two RawSections share the same Part / Title subdivider.

    For CFR: same Part, never definitions.
    For statutes: same parent statute *and* same statute_title (so the
    NEPA preamble §4321 doesn't merge across the Title I boundary into
    §4331).
    For executive orders: same parent EO.
    """
    if a.document_type != b.document_type:
        return False
    if a.document_type == DocumentType.CFR_REGULATION:
        if a.part == "1508" or b.part == "1508":
            return False
        return a.part == b.part
    if a.document_type == DocumentType.STATUTE:
        return (
            a.parent_statute == b.parent_statute
            and a.statute_title == b.statute_title
        )
    if a.document_type == DocumentType.EXECUTIVE_ORDER:
        return a.parent_statute == b.parent_statute
    return False


def _merge_two_chunks(a: Chunk, b: Chunk) -> Chunk:
    """Combine two single-chunk sections into one merged chunk."""
    body = (a.body + " " + b.body).strip()
    return Chunk(
        sources=a.sources + b.sources,
        body=body,
        subsection=None,
        chunk_index=0,
        total_chunks_in_section=1,
        has_table=a.has_table or b.has_table,
        is_definition=False,
        is_merged_siblings=True,
        token_count=count_tokens(body),
    )
