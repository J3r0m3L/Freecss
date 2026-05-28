"""Hybrid relevance scoring (DESIGN.md §3.3, §10.2, §10.3).

Per-watch decision: for one news/social item, compute the best score across all
active watches. Per watch the score is

    rule_score = 1.0 if any active-watch symbol in tickers_final
               = 0.7 if title/desc matches a watch sector/industry keyword
               = 0.0 otherwise
    relevance  = max(rule_score, 0.85 * cosine(headline_emb, watch_profile_emb))

`relevance_source` records the winner: 'symbol' | 'sector' | 'semantic'. Per
§3.3 the discount on the semantic path (×0.85) keeps a pure-vector hit from
ever quite tying a real ticker match.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from server.nlp.finbert import cosine

_SEMANTIC_DISCOUNT = 0.85


@dataclass(frozen=True)
class RelevanceResult:
    score: float                    # 0..1
    source: str                     # 'symbol' | 'sector' | 'semantic'
    matched_watch_id: int | None    # which watch claimed this item (None if none qualified)
    cosine_sim: float = 0.0         # raw cosine, for debugging / observability


def _sector_keywords(meta_json: dict | None) -> list[str]:
    if not meta_json:
        return []
    out: list[str] = []
    for k in ("sector", "industry", "sic_description"):
        v = meta_json.get(k)
        if v:
            out.append(v.lower())
    for kw in meta_json.get("news_keywords", []) or []:
        if kw:
            out.append(kw.lower())
    return out


def rule_relevance_for_watch(
    *,
    tickers_in_item: Iterable[str],
    item_text_lower: str,
    watch_symbol: str,
    watch_meta: dict | None,
) -> tuple[float, str]:
    """Best rule-based score this single watch can claim for one item."""
    if watch_symbol.upper() in {t.upper() for t in (tickers_in_item or ())}:
        return 1.0, "symbol"
    for kw in _sector_keywords(watch_meta):
        if kw and kw in item_text_lower:
            return 0.7, "sector"
    return 0.0, ""


def hybrid_relevance(
    *,
    tickers_in_item: Iterable[str],
    item_text: str,
    item_embedding: list[float] | None,
    watches: list[dict],
) -> RelevanceResult:
    """Score one item across every active watch; return the best.

    `watches`: each dict carries {id, symbol, meta_json (dict|None),
    profile_embedding (list[float]|None)}.
    Returns RelevanceResult with the highest-scoring watch's stats.
    """
    text_lower = (item_text or "").lower()
    best = RelevanceResult(score=0.0, source="", matched_watch_id=None, cosine_sim=0.0)

    for w in watches:
        rule_score, rule_source = rule_relevance_for_watch(
            tickers_in_item=tickers_in_item,
            item_text_lower=text_lower,
            watch_symbol=w["symbol"],
            watch_meta=w.get("meta_json"),
        )
        cos = 0.0
        sem_score = 0.0
        emb = w.get("profile_embedding")
        if item_embedding is not None and emb is not None:
            cos = cosine(item_embedding, emb)
            sem_score = _SEMANTIC_DISCOUNT * max(cos, 0.0)
        if sem_score > rule_score:
            score, source = sem_score, "semantic"
        else:
            score, source = rule_score, rule_source
        if score > best.score:
            best = RelevanceResult(score=score, source=source or "semantic",
                                   matched_watch_id=w["id"], cosine_sim=cos)
    return best
