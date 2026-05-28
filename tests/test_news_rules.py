"""News + X-post severity ladder (DESIGN.md §8)."""
from server.alerts import Severity
from server.alerts.news_rules import NewsAlertInput, evaluate_news


def _inp(relevance: float, sentiment: float, source: str = "symbol",
         direction: str = "BULL") -> NewsAlertInput:
    return NewsAlertInput(relevance=relevance, sentiment=sentiment,
                          relevance_source=source, direction=direction)


def test_critical_requires_all_thresholds_and_ticker_and_adverse():
    hit = evaluate_news(
        kind="news", item_id=1, title="x", url="u",
        inp=_inp(0.97, -0.85, "symbol", "BULL"),
    )
    assert hit is not None
    assert hit.severity == Severity.CRITICAL and hit.adverse is True


def test_sector_only_match_cannot_be_critical():
    """Per §8: the critical tier requires an explicit ticker match. Sector-only
    semantic matches max out at HIGH even when rel/sent are high enough."""
    hit = evaluate_news(
        kind="news", item_id=1, title="x", url="u",
        inp=_inp(0.97, -0.85, "sector", "BULL"),
    )
    assert hit is not None and hit.severity == Severity.HIGH


def test_high_threshold():
    hit = evaluate_news(
        kind="news", item_id=1, title="x", url="u",
        inp=_inp(0.86, -0.71, "semantic", "BULL"),
    )
    assert hit is not None and hit.severity == Severity.HIGH


def test_warn_threshold():
    hit = evaluate_news(
        kind="news", item_id=1, title="x", url="u",
        inp=_inp(0.72, -0.52, "semantic", "BULL"),
    )
    assert hit is not None and hit.severity == Severity.WARN


def test_info_threshold_does_not_require_adverse():
    """Info tier surfaces in the UI regardless of adversity (§8 last row)."""
    hit = evaluate_news(
        kind="news", item_id=1, title="x", url="u",
        inp=_inp(0.6, 0.3, "semantic", "BULL"),
    )
    assert hit is not None and hit.severity == Severity.INFO


def test_aligned_news_blocked_below_info():
    """Above-warn relevance + sentiment but aligned with thesis → no warn/high."""
    hit = evaluate_news(
        kind="news", item_id=1, title="x", url="u",
        inp=_inp(0.86, 0.71, "semantic", "BULL"),  # bull thesis + positive sentiment
    )
    # Drops to info because it's above 0.5 relevance but not adverse.
    assert hit is not None and hit.severity == Severity.INFO


def test_below_floor_returns_none():
    hit = evaluate_news(
        kind="news", item_id=1, title="x", url="u",
        inp=_inp(0.3, -0.9, "semantic", "BULL"),
    )
    assert hit is None


def test_bear_thesis_positive_sentiment_is_adverse():
    hit = evaluate_news(
        kind="news", item_id=1, title="x", url="u",
        inp=_inp(0.97, 0.85, "symbol", "BEAR"),
    )
    assert hit is not None and hit.severity == Severity.CRITICAL
    assert hit.adverse is True
