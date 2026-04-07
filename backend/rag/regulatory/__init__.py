"""Regulatory document ingestion pipeline.

Parses NEPA-style legal PDFs into hierarchically chunked, metadata-rich
records ready for embedding and storage in pgvector. Designed so that the
chunker, breadcrumb builder, embedder, and store layers are document-agnostic;
only the parser carries PDF-specific section detection.
"""
