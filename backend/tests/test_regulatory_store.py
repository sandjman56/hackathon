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
