"""Massive (Polygon) news client (DESIGN.md §10.2).

GET /v2/reference/news?ticker=<X>&order=desc&limit=50
Returns a list of NewsItem dataclasses with the fields the pipeline needs.
Bundled with Stocks Advanced — no incremental billing — but we still log one
api_cost_event row per call (unit_cost=0) so the Usage view shows request
counts.

Falls back to a deterministic stub when MASSIVE_API_KEY is missing or the
HTTP call fails; tests run entirely against the stub via monkeypatch.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger("deleveraging_watch.adapters.massive_news")

_BASE = "https://api.polygon.io/v2/reference/news"
_TIMEOUT_S = 10


@dataclass(frozen=True)
class NewsItem:
    massive_id: str
    title: str
    description: str
    url: str
    published_at: datetime
    publisher: str
    tickers: list[str]
    insights: list[dict]      # raw Massive insights[] for cross-check

    def text_for_scoring(self) -> str:
        return f"{self.title}\n\n{self.description}".strip()


def _api_key() -> str:
    return os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY") or ""


def _parse_ts(s: str) -> datetime:
    # Massive returns ISO8601 with Z; allow no-tz strings as UTC.
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s)
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc)


def _stub_items(ticker: str) -> list[NewsItem]:
    """Two deterministic headlines per call so the pipeline has something to chew on."""
    now = datetime.now(timezone.utc)
    return [
        NewsItem(
            massive_id=f"stub:{ticker}:{int(now.timestamp())}:pos",
            title=f"{ticker} beats earnings estimates, raises full-year guidance",
            description=f"{ticker} reported quarterly results above consensus.",
            url=f"https://example.com/{ticker}/beats",
            published_at=now - timedelta(minutes=15),
            publisher="StubWire",
            tickers=[ticker],
            insights=[],
        ),
        NewsItem(
            massive_id=f"stub:{ticker}:{int(now.timestamp())}:neg",
            title=f"{ticker} faces regulatory probe over antitrust concerns",
            description=f"Regulators announced an investigation into {ticker}.",
            url=f"https://example.com/{ticker}/probe",
            published_at=now - timedelta(minutes=45),
            publisher="StubWire",
            tickers=[ticker],
            insights=[],
        ),
    ]


def fetch_news(ticker: str, *, limit: int = 50) -> list[NewsItem]:
    """One REST call per ticker. Returns [] on any failure."""
    key = _api_key()
    if not key:
        log.debug("MASSIVE_API_KEY missing; returning stub news for %s", ticker)
        return _stub_items(ticker)

    try:
        resp = requests.get(
            _BASE,
            params={"ticker": ticker, "order": "desc", "limit": limit, "apiKey": key},
            timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        data = resp.json() or {}
    except Exception as exc:  # noqa: BLE001
        log.warning("massive news fetch failed for %s: %s", ticker, exc)
        return []

    out: list[NewsItem] = []
    for r in data.get("results", []):
        try:
            out.append(NewsItem(
                massive_id=str(r.get("id") or ""),
                title=r.get("title") or "",
                description=r.get("description") or "",
                url=r.get("article_url") or "",
                published_at=_parse_ts(r.get("published_utc") or ""),
                publisher=((r.get("publisher") or {}).get("name") or ""),
                tickers=[t.upper() for t in (r.get("tickers") or []) if t],
                insights=r.get("insights") or [],
            ))
        except Exception:  # noqa: BLE001
            log.exception("could not parse massive news row for %s", ticker)
    return out


def insights_to_json(insights: list[dict]) -> str:
    """Serialize Massive's insights[] payload for storage on news.massive_insights."""
    try:
        return json.dumps(insights or [])
    except Exception:  # noqa: BLE001
        return "[]"
