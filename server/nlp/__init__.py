"""Local NLP layer (DESIGN.md §3.3, §10).

One FinBERT forward pass per piece of text produces:
- a sentiment scalar in [-1, 1] (= p_positive − p_negative),
- a class label (positive | negative | neutral) + confidence,
- a 768-dim L2-normalized embedding for cosine relevance.

Everything is one-shot deterministic so the news pipeline persists a single row
per item with sentiment + embedding ready. The Haiku-generated profile_text +
its embedding (§10.1) feed the same cosine path.
"""
from __future__ import annotations

from server.nlp.finbert import FinBERTResult, get_finbert
from server.nlp.relevance import RelevanceResult, hybrid_relevance
from server.nlp.ticker_extract import extract_tickers

__all__ = [
    "FinBERTResult",
    "get_finbert",
    "RelevanceResult",
    "hybrid_relevance",
    "extract_tickers",
]
