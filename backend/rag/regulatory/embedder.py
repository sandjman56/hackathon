"""Embedding wrapper for regulatory chunks.

Uses the project's existing :class:`LLMProvider` abstraction (which already
exposes ``embed(text) -> list[float]`` for OpenAI / Gemini / Ollama). The
embedding text is *always* the breadcrumb header concatenated with the
chunk body — embedding the body alone would lose the strongest retrieval
signal.

Sync ``LLMProvider.embed`` calls are wrapped in ``asyncio.to_thread`` so
batch ingestion can run with bounded concurrency without blocking the
event loop.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .breadcrumbs import build_breadcrumb
from .chunker import Chunk

logger = logging.getLogger("eia.rag.regulatory.embedder")


def embedding_text(chunk: Chunk, breadcrumb: str | None = None) -> str:
    """Compose the exact string that will be embedded for a chunk."""
    if breadcrumb is None:
        breadcrumb = build_breadcrumb(chunk)
    return f"{breadcrumb}\n\n{chunk.body}"


async def embed_chunk(chunk: Chunk, provider: Any) -> tuple[str, list[float]]:
    """Embed one chunk asynchronously and return ``(breadcrumb, vector)``."""
    breadcrumb = build_breadcrumb(chunk)
    text = embedding_text(chunk, breadcrumb)
    vector = await asyncio.to_thread(provider.embed, text)
    return breadcrumb, vector


async def embed_chunks(
    chunks: list[Chunk],
    provider: Any,
    concurrency: int = 4,
) -> list[tuple[str, list[float]]]:
    """Embed many chunks with bounded concurrency.

    Args:
        chunks: Chunks to embed (order preserved in the result).
        provider: An :class:`LLMProvider` instance with ``embed()``.
        concurrency: Max in-flight embedding calls. Most providers
            (Gemini free tier, OpenAI) rate-limit aggressively, so 4 is
            a safe default.

    Returns:
        A list of ``(breadcrumb, vector)`` tuples in the same order as
        the input chunks.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _one(c: Chunk) -> tuple[str, list[float]]:
        async with sem:
            try:
                return await embed_chunk(c, provider)
            except Exception:
                logger.exception(
                    "Embedding failed for %s",
                    c.sources[0].citation if c.sources else "<unknown>",
                )
                raise

    return await asyncio.gather(*(_one(c) for c in chunks))


def detect_embedding_dimension(provider: Any) -> int:
    """Probe the provider once to learn its output dimension.

    The dimension varies by provider/model — OpenAI text-embedding-3-small
    is 1536, Gemini text-embedding-004 is 768, MiniLM is 384 — and the
    pgvector column type must match exactly.
    """
    vec = provider.embed("dimension probe")
    return len(vec)
