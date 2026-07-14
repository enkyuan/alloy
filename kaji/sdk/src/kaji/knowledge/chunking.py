"""Deterministic, dependency-free text chunking.

A character-window chunker with overlap. Deterministic so tests are stable and
the same document always produces the same chunks (and therefore the same
downstream cache keys). Token-aware chunking can be layered later behind the
same function signature.
"""

from typing import List


def chunk_text(text: str, size: int = 1000, overlap: int = 200) -> List[str]:
    """Split ``text`` into overlapping character windows.

    Args:
        text: the source text. Empty/whitespace-only yields ``[]``.
        size: max characters per chunk. Must be > 0.
        overlap: characters shared between consecutive chunks. Must be < size.

    Returns:
        A list of chunk strings in document order.
    """
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= size:
        raise ValueError("overlap must be less than size")

    stripped = text.strip()
    if not stripped:
        return []

    step = size - overlap
    chunks: List[str] = []
    start = 0
    n = len(stripped)
    while start < n:
        chunks.append(stripped[start : start + size])
        start += step
    return chunks
