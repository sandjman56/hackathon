"""Shared tokenizer helper used by regulatory and evaluation chunkers.

Both chunkers need the same cl100k_base encoder. Importing from either
chunker module would create a circular import via their parsers, so the
encoder lives here.
"""
from __future__ import annotations

import tiktoken

_ENCODER = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Return the cl100k_base token count for ``text``."""
    return len(_ENCODER.encode(text))


def encode(text: str) -> list[int]:
    return _ENCODER.encode(text)


def decode(tokens: list[int]) -> str:
    return _ENCODER.decode(tokens)
