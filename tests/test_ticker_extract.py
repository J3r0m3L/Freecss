"""Ticker extraction (DESIGN.md §10.2, §10.3)."""
from server.nlp.ticker_extract import extract_tickers, union_tickers


def test_cashtag_always_matches_without_watchlist():
    text = "Watching $AAPL and $BRK.B today, ignoring AI hype."
    assert extract_tickers(text) == ["AAPL", "BRK.B"]


def test_bare_uppercase_requires_watchlist_membership():
    text = "AAPL beats; GDP up; AI sector mixed."
    # Without a watchlist, only English-word collisions would surface — so we
    # return nothing for bare-uppercase matches.
    assert extract_tickers(text) == []
    # With a watchlist, only the whitelisted symbol survives.
    assert extract_tickers(text, watchlist=["AAPL"]) == ["AAPL"]


def test_dedupe_and_order_preserved():
    text = "$MSFT outperformed; later MSFT reported; also $AAPL up"
    assert extract_tickers(text, watchlist=["MSFT", "AAPL"]) == ["MSFT", "AAPL"]


def test_union_with_massive_tickers():
    text = "$AAPL beats; QQQ also mentioned"
    out = union_tickers(["TSLA"], text, watchlist=["QQQ", "AAPL"])
    # Massive's contribution first, then regex finds.
    assert out == ["TSLA", "AAPL", "QQQ"]


def test_empty_text_safe():
    assert extract_tickers("") == []
    assert extract_tickers(None) == []  # type: ignore[arg-type]
    assert union_tickers([], "") == []
