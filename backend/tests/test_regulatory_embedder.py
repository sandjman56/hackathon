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
