"""Thin alias for detect_embedding_dimension so EIS ingest doesn't pull
in the regulatory parser chain."""
from __future__ import annotations

from rag.regulatory.embedder import detect_embedding_dimension  # noqa: F401
