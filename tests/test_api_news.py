"""/api/news + /api/instrument/<sym>/news (DESIGN.md §7.1, §11.B)."""


def test_empty_global_news(client):
    assert client.get("/api/news").json == []


def test_global_news_union_of_news_and_social(
    client, make_watch_with_profile, seed_news, seed_social_post,
):
    make_watch_with_profile("AAPL", "BULL")
    seed_news(title="AAPL news 1")
    seed_social_post(body="AAPL tweet 1 with $AAPL")
    body = client.get("/api/news").json
    kinds = {item["kind"] for item in body}
    assert kinds == {"news", "x"}


def test_source_filter_narrows(client, make_watch_with_profile, seed_news, seed_social_post):
    make_watch_with_profile("AAPL", "BULL")
    seed_news()
    seed_social_post()
    news_only = client.get("/api/news?source=news").json
    x_only = client.get("/api/news?source=x").json
    assert {i["kind"] for i in news_only} == {"news"}
    assert {i["kind"] for i in x_only} == {"x"}


def test_sentiment_filter(client, make_watch_with_profile, seed_news):
    make_watch_with_profile("AAPL", "BULL")
    seed_news(title="pos", sentiment=0.8, sentiment_label="positive")
    seed_news(title="neg", sentiment=-0.8, sentiment_label="negative")
    pos = client.get("/api/news?sentiment=pos&source=news").json
    neg = client.get("/api/news?sentiment=neg&source=news").json
    assert {i["title"] for i in pos} == {"pos"}
    assert {i["title"] for i in neg} == {"neg"}


def test_min_relevance_floor(client, make_watch_with_profile, seed_news):
    make_watch_with_profile("AAPL", "BULL")
    seed_news(title="lo", relevance=0.4)   # below default floor of 0.5
    seed_news(title="hi", relevance=0.9)
    body = client.get("/api/news?source=news").json
    assert {i["title"] for i in body} == {"hi"}


def test_per_symbol_news_filters_by_ticker(
    client, make_watch_with_profile, seed_news,
):
    make_watch_with_profile("AAPL", "BULL")
    make_watch_with_profile("MSFT", "BULL")
    seed_news(title="apple", tickers=["AAPL"])
    seed_news(title="msft", tickers=["MSFT"])
    body = client.get("/api/instrument/AAPL/news").json
    assert {i["title"] for i in body} == {"apple"}


def test_per_symbol_news_unknown_404(client):
    assert client.get("/api/instrument/ZZZZ/news").status_code == 404
