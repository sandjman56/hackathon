"""Offline embedding provider for tests.

Returns deterministic, fixed-dimension vectors so ingestion tests run
without hitting OpenAI/Gemini.
"""
from __future__ import annotations


class StubEmbeddingProvider:
    provider_name = "stub"

    def __init__(self, dim: int = 8):
        self.dim = dim
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        # Deterministic but not all-zero so cosine search has signal
        h = abs(hash(text)) % 1000
        return [(h + i) / 1000.0 for i in range(self.dim)]
