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
    if section.section_number:
        sec_key = section.section_number
    else:
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
