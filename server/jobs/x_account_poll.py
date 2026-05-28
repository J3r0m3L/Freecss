"""x_account_poll (§7.3, §10.3). Every 1 minute — one X API call per active
social_account_watch (most return zero new tweets and are free). New tweets
land in `social_post` and may fire `social_x` alerts via the news-ladder.

Per-post billing rows are written inside x_api.fetch_tweets — this job doesn't
need to touch api_cost_event directly.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from server.adapters.x_api import fetch_tweets, resolve_user_id
from server.alerts import engine
from server.alerts.news_rules import (
    PERSIST_MIN_RELEVANCE, NewsAlertInput, evaluate_news,
)
from server.db import execute, one, rows
from server.jobs import record_run
from server.jobs.massive_news_poll import _active_watches
from server.nlp.finbert import get_finbert
from server.nlp.relevance import hybrid_relevance
from server.nlp.ticker_extract import extract_tickers

log = logging.getLogger("deleveraging_watch.jobs.x_account_poll")


def _active_accounts() -> list[dict]:
    return rows(
        "SELECT id, handle, label, external_id, last_post_id "
        "FROM social_account_watch WHERE active=1 ORDER BY id"
    )


def _ensure_external_id(account: dict) -> str | None:
    if account["external_id"]:
        return account["external_id"]
    ext_id = resolve_user_id(account["handle"])
    if not ext_id:
        return None
    execute("UPDATE social_account_watch SET external_id=? WHERE id=?",
            (ext_id, account["id"]))
    return ext_id


def _persist_post(account_id: int, tweet, *, tickers: list[str],
                  relevance: float, relevance_source: str,
                  sentiment: float, sentiment_label: str,
                  sentiment_conf: float) -> int | None:
    """Insert one social_post; returns id or None on UNIQUE collision."""
    try:
        cur = execute(
            "INSERT INTO social_post(source, account_id, external_post_id, posted_at, "
            "fetched_at, body, url, tickers_json, relevance, relevance_source, "
            "sentiment, sentiment_label, sentiment_conf) "
            "VALUES('x',?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                account_id, tweet.external_post_id, tweet.posted_at.isoformat(),
                datetime.now(timezone.utc).isoformat(),
                tweet.body, tweet.url, json.dumps(tickers),
                round(relevance, 4), relevance_source,
                round(sentiment, 4), sentiment_label, round(sentiment_conf, 4),
            ),
        )
        return cur.lastrowid
    except Exception:  # noqa: BLE001
        log.debug("social_post insert skipped (likely dupe): %s", tweet.external_post_id)
        return None


def _broadcast(socketio, post_id: int, tweet, *, account: dict,
               relevance: float, relevance_source: str,
               sentiment: float, sentiment_label: str, sentiment_conf: float,
               tickers: list[str]) -> None:
    if socketio is None:
        return
    socketio.emit("news", {
        "id": post_id, "kind": "x",
        "title": None,
        "body": tweet.body,
        "url": tweet.url,
        "source": f"@{account['handle']} ({account.get('label') or ''})".strip(),
        "posted_at": tweet.posted_at.isoformat(),
        "relevance": round(relevance, 4),
        "relevance_source": relevance_source,
        "sentiment": round(sentiment, 4),
        "sentiment_label": sentiment_label,
        "sentiment_conf": round(sentiment_conf, 4),
        "tickers": tickers,
    })


def run(socketio=None) -> None:
    if socketio is None:
        try:
            from server.app import socketio as _sio
            socketio = _sio
        except Exception:  # noqa: BLE001
            socketio = None

    with record_run("x_account_poll") as result:
        watches = _active_watches()
        watchlist_syms = [w["symbol"] for w in watches]
        finbert = get_finbert()
        accounts = _active_accounts()
        persisted = 0

        for acct in accounts:
            ext_id = _ensure_external_id(acct)
            if not ext_id:
                continue
            tweets = fetch_tweets(acct["handle"], ext_id,
                                  since_id=acct["last_post_id"],
                                  ref_job_run="x_account_poll")
            if not tweets:
                execute("UPDATE social_account_watch SET last_polled_at=? WHERE id=?",
                        (datetime.now(timezone.utc).isoformat(), acct["id"]))
                continue

            for tw in tweets:
                tickers = extract_tickers(tw.body, watchlist=watchlist_syms)
                fin = finbert.score(tw.body)
                rel = hybrid_relevance(
                    tickers_in_item=tickers, item_text=tw.body,
                    item_embedding=fin.embedding, watches=watches,
                )
                if rel.score < PERSIST_MIN_RELEVANCE:
                    continue
                post_id = _persist_post(
                    acct["id"], tw, tickers=tickers,
                    relevance=rel.score, relevance_source=rel.source,
                    sentiment=fin.sentiment, sentiment_label=fin.label,
                    sentiment_conf=fin.conf,
                )
                if post_id is None:
                    continue
                persisted += 1
                _broadcast(
                    socketio, post_id, tw, account=acct,
                    relevance=rel.score, relevance_source=rel.source,
                    sentiment=fin.sentiment, sentiment_label=fin.label,
                    sentiment_conf=fin.conf, tickers=tickers,
                )

                matched = next((w for w in watches if w["id"] == rel.matched_watch_id), None)
                if matched is None:
                    continue
                hit = evaluate_news(
                    kind="social_x", item_id=post_id, title=tw.body[:120],
                    url=tw.url,
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

            # Bookmark advance.
            newest_id = max((t.external_post_id for t in tweets), default=acct["last_post_id"])
            execute(
                "UPDATE social_account_watch SET last_post_id=?, last_polled_at=? "
                "WHERE id=?",
                (newest_id, datetime.now(timezone.utc).isoformat(), acct["id"]),
            )

        result["rows"] = persisted
