"""Retrieval reranking.

Reranks candidate retrieved items by relevance to the query using embeddings
(cosine) when available, falling back to lexical overlap. Optional LLM rerank
can be layered on top by callers.
"""

import logging
import re

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[a-z0-9]{3,}")


def _tokens(text: str) -> set:
    return set(_WORD.findall((text or "").lower()))


def _cosine(a, b) -> float:
    try:
        import numpy as np
        va = np.asarray(a, dtype=float)
        vb = np.asarray(b, dtype=float)
        na = float(np.linalg.norm(va))
        nb = float(np.linalg.norm(vb))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return float(np.dot(va, vb) / (na * nb))
    except Exception:
        return 0.0


def rerank(query: str, items, top_k: int = 6, embed_fn=None, key: str = "text"):
    if not items:
        return []
    text_of = (lambda it: it.get(key, "")) if isinstance(items[0], dict) else (lambda it: str(it))

    scored = []
    if embed_fn is not None:
        try:
            qv = embed_fn([query])[0]
            vecs = embed_fn([text_of(it) for it in items])
            for it, v in zip(items, vecs):
                scored.append((_cosine(qv, list(v)), it))
        except Exception:
            logger.debug("Embedding rerank failed; using lexical", exc_info=True)
            scored = []

    if not scored:
        qt = _tokens(query)
        for it in items:
            t = _tokens(text_of(it))
            score = (len(qt & t) / len(qt)) if qt else 0.0
            scored.append((score, it))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _s, it in scored[:max(1, top_k)]]