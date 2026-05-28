"""News & X-post alert severity ladders (DESIGN.md §8).

Both ladders use the same shape: relevance × |sentiment| × ticker-match
strength → severity. The strict `critical` tier (relevance ≥ 0.95, |sent| ≥ 0.8,
explicit ticker match, adverse) reflects "only this pages outside work hours."

Adverse polarity for news/social mirrors the price model: a negative-sentiment
item is adverse to a BULL thesis; a positive-sentiment item is adverse to a
BEAR thesis. Neutral or low-confidence items are not adverse.
"""
from __future__ import annotations

from dataclasses import dataclass

from server.alerts import Severity
from server.alerts.rules import RuleHit

# Below this relevance, we don't even persist the item (§10.2, §10.3).
PERSIST_MIN_RELEVANCE = 0.5


@dataclass(frozen=True)
class NewsAlertInput:
    relevance: float
    sentiment: float           # -1..1
    relevance_source: str      # 'symbol' | 'sector' | 'semantic'
    direction: str             # 'BULL' | 'BEAR' — the matched watch's thesis


def _is_adverse(direction: str, sentiment: float) -> bool:
    if direction == "BULL":
        return sentiment < -0.1
    return sentiment > 0.1  # BEAR


def _severity(*, relevance: float, abs_sent: float, ticker_match: bool,
              adverse: bool) -> Severity | None:
    """The §8 ladder. None means "below threshold, don't alert"."""
    if relevance >= 0.95 and abs_sent >= 0.8 and ticker_match and adverse:
        return Severity.CRITICAL
    if relevance >= 0.85 and abs_sent >= 0.7 and adverse:
        return Severity.HIGH
    if relevance >= 0.7 and abs_sent >= 0.5 and adverse:
        return Severity.WARN
    if relevance >= 0.5:
        return Severity.INFO  # UI-only; routed/dropped by quiet hours
    return None


def evaluate_news(*, kind: str, item_id: int, title: str, url: str,
                  inp: NewsAlertInput) -> RuleHit | None:
    """Build a RuleHit for one news/X item, or None if it doesn't clear the floor."""
    abs_sent = abs(inp.sentiment)
    ticker_match = inp.relevance_source == "symbol"
    adverse = _is_adverse(inp.direction, inp.sentiment)
    sev = _severity(relevance=inp.relevance, abs_sent=abs_sent,
                    ticker_match=ticker_match, adverse=adverse)
    if sev is None:
        return None
    return RuleHit(
        kind=kind, severity=sev, adverse=adverse,
        payload={
            "id": item_id, "title": title, "url": url,
            "relevance": round(inp.relevance, 3),
            "relevance_source": inp.relevance_source,
            "sentiment": round(inp.sentiment, 3),
            "abs_sentiment": round(abs_sent, 3),
            "ticker_match": ticker_match,
            "thesis": inp.direction,
        },
    )
