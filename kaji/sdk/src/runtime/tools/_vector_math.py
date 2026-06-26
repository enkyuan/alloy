"""Shared vector math for RAG (tool selection and document retrieval).

Lives here, low in the tool layer, so both the tool retriever
(``runtime/tools/retriever.py``) and the document RAG store
(``knowledge/store.py``) can import it without a dependency cycle.
"""

import math
from typing import List


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(a * a for a in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)
