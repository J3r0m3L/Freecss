"""News + X-post unified feed (DESIGN.md §7.1, §11.B, §11.C #4).

`/api/news` returns the global union (across all active watches) of Massive
news rows and X social_post rows. `/api/instrument/<symbol>/news` is the same
union narrowed to one watch's ticker.

Item shape stays uniform so the React layer can render either source without
discriminating beyond the `kind` field:
    {id, kind ∈ {'news','x'}, title?, body, url, source, posted_at,
     relevance, relevance_source, sentiment, sentiment_label, sentiment_conf, tickers[]}
"""
from __future__ import annotations

import json

from flask import Blueprint, jsonify, request

from server.db import one, rows

bp = Blueprint("news", __name__, url_prefix="/api")

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _news_view(r: dict) -> dict:
    return {
        "id": r["id"], "kind": "news",
        "title": r["title"], "body": r["snippet"], "url": r["url"],
        "source": r["source"], "posted_at": r["published_at"],
        "relevance": r["relevance"], "relevance_source": r["relevance_source"],
        "sentiment": r["sentiment"], "sentiment_label": r["sentiment_label"],
        "sentiment_conf": r["sentiment_conf"],
        "tickers": json.loads(r["tickers_json"]) if r["tickers_json"] else [],
    }


def _social_view(r: dict) -> dict:
    handle = r["handle"]
    label = r["label"] or ""
    src = f"@{handle}" + (f" ({label})" if label else "")
    return {
        "id": r["id"], "kind": "x",
        "title": None, "body": r["body"], "url": r["url"],
        "source": src, "posted_at": r["posted_at"],
        "relevance": r["relevance"], "relevance_source": r["relevance_source"],
        "sentiment": r["sentiment"], "sentiment_label": r["sentiment_label"],
        "sentiment_conf": r["sentiment_conf"],
        "tickers": json.loads(r["tickers_json"]) if r["tickers_json"] else [],
    }


def _parse_filters() -> dict:
    args = request.args
    return {
        "since": args.get("since"),
        "min_relevance": float(args.get("min_relevance", 0.5)),
        "sentiment": (args.get("sentiment") or "any").lower(),  # any|pos|neg
        "source": (args.get("source") or "all").lower(),        # news|x|all
        "limit": min(int(args.get("limit", _DEFAULT_LIMIT)), _MAX_LIMIT),
    }


def _sentiment_clause(sentiment: str, col: str = "sentiment") -> tuple[str, tuple]:
    if sentiment == "pos":
        return f" AND {col} > 0", ()
    if sentiment == "neg":
        return f" AND {col} < 0", ()
    return "", ()


def _collect(f: dict, *, ticker: str | None) -> list[dict]:
    items: list[dict] = []

    if f["source"] in ("news", "all"):
        q = "SELECT * FROM news WHERE relevance >= ?"
        p: list = [f["min_relevance"]]
        if f["since"]:
            q += " AND published_at >= ?"
            p.append(f["since"])
        sc, _ = _sentiment_clause(f["sentiment"])
        q += sc
        if ticker:
            q += " AND tickers_json LIKE ?"
            p.append(f'%"{ticker.upper()}"%')
        q += " ORDER BY published_at DESC LIMIT ?"
        p.append(f["limit"])
        items.extend(_news_view(r) for r in rows(q, tuple(p)))

    if f["source"] in ("x", "all"):
        q = ("SELECT p.*, a.handle, a.label FROM social_post p "
             "JOIN social_account_watch a ON a.id=p.account_id "
             "WHERE p.relevance >= ?")
        p = [f["min_relevance"]]
        if f["since"]:
            q += " AND p.posted_at >= ?"
            p.append(f["since"])
        sc, _ = _sentiment_clause(f["sentiment"], col="p.sentiment")
        q += sc
        if ticker:
            q += " AND p.tickers_json LIKE ?"
            p.append(f'%"{ticker.upper()}"%')
        q += " ORDER BY p.posted_at DESC LIMIT ?"
        p.append(f["limit"])
        items.extend(_social_view(r) for r in rows(q, tuple(p)))

    items.sort(key=lambda x: x.get("posted_at") or "", reverse=True)
    return items[: f["limit"]]


@bp.get("/news")
def global_news():
    return jsonify(_collect(_parse_filters(), ticker=request.args.get("ticker")))


@bp.get("/instrument/<symbol>/news")
def per_symbol_news(symbol: str):
    symbol = symbol.upper()
    if one("SELECT 1 FROM instrument WHERE symbol=?", (symbol,)) is None:
        return jsonify({"error": "instrument not found"}), 404
    return jsonify(_collect(_parse_filters(), ticker=symbol))
