"""Regulatory document ingestion pipeline.

Parses legal PDFs into hierarchically chunked, metadata-rich records ready
for embedding and storage in pgvector. Supports multiple parser backends:

- ``parser.py`` — Federal CFR/NEPA-style scanned reprints
- ``parser_pa_code.py`` — PA Code browser-printed PDFs

The chunker, breadcrumb builder, embedder, and store layers are
document-agnostic; only the parser carries PDF-specific section detection.
The ingest service auto-detects the correct parser from page content.
"""
