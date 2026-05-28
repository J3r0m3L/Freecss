"""Hybrid relevance scoring (DESIGN.md §3.3, §10.2/§10.3)."""
from server.nlp.relevance import hybrid_relevance, rule_relevance_for_watch


def test_symbol_match_beats_sector():
    score, source = rule_relevance_for_watch(
        tickers_in_item=["AAPL"], item_text_lower="apple beats",
        watch_symbol="AAPL", watch_meta={"sector": "Technology"},
    )
    assert (score, source) == (1.0, "symbol")


def test_sector_keyword_match():
    score, source = rule_relevance_for_watch(
        tickers_in_item=[], item_text_lower="technology sector outperformed today",
        watch_symbol="MSFT", watch_meta={"sector": "Technology"},
    )
    assert score == 0.7 and source == "sector"


def test_no_match_returns_zero():
    score, _ = rule_relevance_for_watch(
        tickers_in_item=["XYZ"], item_text_lower="utilities up; bonds down",
        watch_symbol="AAPL", watch_meta={"sector": "Technology"},
    )
    assert score == 0.0


def test_hybrid_picks_best_watch():
    watches = [
        {"id": 1, "symbol": "AAPL", "meta_json": {"sector": "Technology"},
         "profile_embedding": [1.0, 0.0]},
        {"id": 2, "symbol": "TSLA", "meta_json": {"sector": "Auto"},
         "profile_embedding": [0.0, 1.0]},
    ]
    # Ticker AAPL → symbol match (score 1.0) for watch 1; nothing for watch 2.
    rel = hybrid_relevance(
        tickers_in_item=["AAPL"], item_text="aapl rallies",
        item_embedding=[0.5, 0.5], watches=watches,
    )
    assert rel.score == 1.0 and rel.source == "symbol" and rel.matched_watch_id == 1


def test_semantic_path_with_discount():
    # No ticker / sector hit, but the embedding is identical to watch 1's profile.
    # 0.85 × cosine(1.0) = 0.85 → wins over rule_score=0 even with the discount.
    watches = [
        {"id": 1, "symbol": "AAPL", "meta_json": {"sector": "Technology"},
         "profile_embedding": [1.0, 0.0]},
    ]
    rel = hybrid_relevance(
        tickers_in_item=[], item_text="unrelated text",
        item_embedding=[1.0, 0.0], watches=watches,
    )
    assert abs(rel.score - 0.85) < 1e-6
    assert rel.source == "semantic" and rel.matched_watch_id == 1


def test_no_watches_or_no_embedding_returns_zero():
    assert hybrid_relevance(tickers_in_item=[], item_text="x",
                            item_embedding=None, watches=[]).score == 0.0
    # No embedding on either side → semantic path skipped, no rules to fall back to.
    rel = hybrid_relevance(
        tickers_in_item=[], item_text="x", item_embedding=None,
        watches=[{"id": 1, "symbol": "AAPL", "meta_json": None,
                  "profile_embedding": None}],
    )
    assert rel.score == 0.0
