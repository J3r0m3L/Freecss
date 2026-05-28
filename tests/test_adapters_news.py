"""Massive news + Finnhub + X adapters — stub behavior + cost-event side effects."""
from datetime import date

import server.adapters.massive_news as mn
from server.adapters.finnhub import fetch_earnings, fetch_profile
from server.adapters.x_api import fetch_tweets, resolve_user_id
from server.db import one, rows


def test_massive_news_stub_returns_two_deterministic_items(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    items = mn.fetch_news("AAPL")
    assert len(items) == 2
    titles = [i.title for i in items]
    assert any("beats" in t.lower() for t in titles)
    assert any("probe" in t.lower() for t in titles)
    assert all("AAPL" in i.tickers for i in items)


def test_massive_news_text_for_scoring_joins_title_and_description():
    item = mn._stub_items("AAPL")[0]
    txt = item.text_for_scoring()
    assert item.title in txt and item.description in txt


def test_finnhub_profile_stub_when_no_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    p = fetch_profile("AAPL")
    assert p.sector and p.industry and p.country == "US"
    assert "AAPL" in (p.description or "")


def test_finnhub_earnings_stub_returns_one_per_symbol(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    today = date.today()
    events = fetch_earnings(["AAPL", "MSFT"], frm=today, to=today)
    assert {e.symbol for e in events} == {"AAPL", "MSFT"}


def test_x_resolve_user_id_stub(monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    assert resolve_user_id("SecTreasury") == "stub-SecTreasury"
    # No api_cost_event written for the stub path — only the real network call bills.
    assert rows("SELECT * FROM api_cost_event WHERE source='x:user_read'") == []


def test_x_fetch_tweets_first_poll_returns_one(monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    tweets = fetch_tweets("SecTreasury", "stub-id", since_id=None)
    assert len(tweets) == 1
    assert "tariffs" in tweets[0].body.lower()


def test_x_fetch_tweets_subsequent_poll_empty(monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    assert fetch_tweets("SecTreasury", "stub-id", since_id="last-1") == []
    # Subsequent polls returning nothing should NOT produce cost events.
    assert one("SELECT COUNT(*) c FROM api_cost_event") == {"c": 0}
