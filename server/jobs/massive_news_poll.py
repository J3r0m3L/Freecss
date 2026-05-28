"""massive_news_poll (§7.3, §10.2). Hourly — one REST call per active watch
instrument. Dedupe against news.massive_id, score with FinBERT + hybrid
relevance, persist to `news`, broadcast on the `news` WS channel, route any
alert-grade items through engine.fire().
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from server.adapters.massive_news import NewsItem, fetch_news, insights_to_json
from server.alerts import engine
from server.alerts.news_rules import (
    PERSIST_MIN_RELEVANCE, NewsAlertInput, evaluate_news,
)
from server.db import execute, get_db, one, rows
from server.jobs import record_run
from server.nlp.finbert import blob_to_embedding, get_finbert
from server.nlp.relevance import hybrid_relevance
from server.nlp.ticker_extract import union_tickers

log = logging.getLogger("deleveraging_watch.jobs.massive_news_poll")


def _active_watches() -> list[dict]:
    """Watches enriched with meta_json (parsed) + profile_embedding (decoded)."""
    raw = rows(
        "SELECT w.id, w.direction, i.id AS instrument_id, i.symbol, "
        "       i.meta_json, i.profile_embedding "
        "FROM watch w JOIN instrument i ON i.id=w.instrument_id WHERE w.active=1"
    )
    out: list[dict] = []
    for r in raw:
        out.append({
            "id": r["id"],
            "direction": r["direction"],
            "instrument_id": r["instrument_id"],
            "symbol": r["symbol"],
            "meta_json": json.loads(r["meta_json"]) if r["meta_json"] else None,
            "profile_embedding": blob_to_embedding(r["profile_embedding"]),
        })
    return out


def _already_ingested(massive_id: str) -> bool:
    return one("SELECT 1 FROM news WHERE massive_id=?", (massive_id,)) is not None


def _persist_news(item: NewsItem, *, tickers: list[str], relevance: float,
                  relevance_source: str, sentiment: float, sentiment_label: str,
                  sentiment_conf: float) -> int | None:
    """Insert a news row; returns the new id, or None if URL is a duplicate."""
    try:
        cur = execute(
            "INSERT INTO news(fetched_at, source, url, title, snippet, published_at, "
            "massive_id, massive_insights, relevance, relevance_source, "
            "sentiment, sentiment_label, sentiment_conf, tickers_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                datetime.now(timezone.utc).isoformat(),
                item.publisher, item.url, item.title, item.description,
                item.published_at.isoformat(), item.massive_id,
                insights_to_json(item.insights),
                round(relevance, 4), relevance_source,
                round(sentiment, 4), sentiment_label, round(sentiment_conf, 4),
                json.dumps(tickers),
            ),
        )
        return cur.lastrowid
    except Exception:  # noqa: BLE001 — URL UNIQUE collision is the expected dupe path
        log.debug("news insert skipped (likely duplicate url): %s", item.url)
        return None


def _broadcast(socketio, news_id: int, item: NewsItem, *, watches: list[dict],
               relevance: float, relevance_source: str, sentiment: float,
               sentiment_label: str, sentiment_conf: float, tickers: list[str]) -> None:
    payload = {
        "id": news_id, "kind": "news",
        "title": item.title, "body": item.description, "url": item.url,
        "source": item.publisher, "posted_at": item.published_at.isoformat(),
        "relevance": round(relevance, 4),
        "relevance_source": relevance_source,
        "sentiment": round(sentiment, 4),
        "sentiment_label": sentiment_label,
        "sentiment_conf": round(sentiment_conf, 4),
        "tickers": tickers,
    }
    if socketio is not None:
        socketio.emit("news", payload)


def run(socketio=None) -> None:
    """Poll Massive's news endpoint for every active watch and score the new items.

    `socketio` is injected for testing; production calls leave it None and we
    look it up from server.app late."""
    if socketio is None:
        try:
            from server.app import socketio as _sio
            socketio = _sio
        except Exception:  # noqa: BLE001
            socketio = None

    with record_run("massive_news_poll") as result:
        watches = _active_watches()
        if not watches:
            result["rows"] = 0
            return

        symbols = sorted({w["symbol"] for w in watches})
        watchlist_syms = [w["symbol"] for w in watches]
        finbert = get_finbert()
        persisted = 0

        # api_cost_event: one row per call (units = req count, cost = $0).
        execute(
            "INSERT INTO api_cost_event(source, units, unit_cost_usd, cost_usd, "
            "ref_job_run, ref_endpoint) VALUES('massive:news',?,0,0,?,?)",
            (len(symbols), "massive_news_poll", "GET /v2/reference/news"),
        )

        for sym in symbols:
            for item in fetch_news(sym):
                if not item.massive_id or _already_ingested(item.massive_id):
                    continue
                text = item.text_for_scoring()
                tickers = union_tickers(item.tickers, text, watchlist=watchlist_syms)
                fin = finbert.score(text)
                rel = hybrid_relevance(
                    tickers_in_item=tickers, item_text=text,
                    item_embedding=fin.embedding, watches=watches,
                )
                if rel.score < PERSIST_MIN_RELEVANCE:
                    continue
                news_id = _persist_news(
                    item, tickers=tickers,
                    relevance=rel.score, relevance_source=rel.source,
                    sentiment=fin.sentiment, sentiment_label=fin.label,
                    sentiment_conf=fin.conf,
                )
                if news_id is None:
                    continue
                persisted += 1
                _broadcast(
                    socketio, news_id, item, watches=watches,
                    relevance=rel.score, relevance_source=rel.source,
                    sentiment=fin.sentiment, sentiment_label=fin.label,
                    sentiment_conf=fin.conf, tickers=tickers,
                )

                # Alert ladder runs against the best-matched watch only.
                matched = next((w for w in watches if w["id"] == rel.matched_watch_id), None)
                if matched is None:
                    continue
                hit = evaluate_news(
                    kind="news", item_id=news_id, title=item.title, url=item.url,
                    inp=NewsAlertInput(
                        relevance=rel.score, sentiment=fin.sentiment,
                        relevance_source=rel.source, direction=matched["direction"],
                    ),
                )
                if hit is None:
                    continue
                engine.fire(
                    instrument_id=matched["instrument_id"], symbol=matched["symbol"],
                    direction=matched["direction"], hit=hit, socketio=socketio,
                )
        result["rows"] = persisted
