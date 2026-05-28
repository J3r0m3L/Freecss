"""Shared pytest fixtures (DESIGN.md §18).

Per-test isolation: every test starts with a fresh SQLite file at a tempfile
path, with the schema applied and seeds loaded. No test touches the real
`deleveraging_watch.db`.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# CRITICAL: set DW_DB_PATH BEFORE any `server` import, so the config singleton
# (which reads env at construction time) points at the tempfile path.
_TMPDIR = Path(tempfile.mkdtemp(prefix="dw-tests-"))
os.environ["DW_DB_PATH"] = str(_TMPDIR / "test.db")
# Don't shell out to Pushover or any HTTP service from tests.
os.environ.setdefault("DW_NOTIFIER", "console")
# Phase 2: always use the deterministic stub backends — no 400MB FinBERT
# checkpoint, no Anthropic network calls, no external HTTP.
os.environ.setdefault("DW_FINBERT_BACKEND", "stub")
os.environ.setdefault("DW_PROFILE_TEXT_BACKEND", "stub")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Drop and re-init the test DB (incl. seeds) before each test."""
    from server import db as db_mod

    # Close any cached thread-local connection so its file handle releases.
    conn = getattr(db_mod._local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        finally:
            db_mod._local.conn = None

    base = Path(os.environ["DW_DB_PATH"])
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(base) + suffix)
        if p.exists():
            p.unlink()

    db_mod.init_db()
    yield


@pytest.fixture
def app():
    """Flask app with background workers disabled — tests drive jobs directly."""
    from server.app import create_app

    return create_app(start_background=False)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_watch():
    """Insert an instrument + active watch; return (instrument_id, watch_id).

    If the symbol already exists (e.g. seeded as a factor_bucket candidate like
    SPY/QQQ), the existing instrument row is reused — just a fresh watch attaches.
    """
    from server.db import execute, one

    def _mk(symbol: str, direction: str = "BULL") -> tuple[int, int]:
        existing = one("SELECT id FROM instrument WHERE symbol=?", (symbol,))
        if existing:
            iid = existing["id"]
        else:
            cur = execute(
                "INSERT INTO instrument(symbol, display_name, asset_class, data_adapter) "
                "VALUES(?,?,?,?)",
                (symbol, symbol, "equity", "stub"),
            )
            iid = cur.lastrowid
        cur = execute(
            "INSERT INTO watch(instrument_id, direction) VALUES(?,?)",
            (iid, direction),
        )
        return iid, cur.lastrowid

    return _mk


@pytest.fixture
def seed_ticks():
    """Write a linear price walk into `tick` ending at "now"."""
    from server.db import execute

    def _seed(iid: int, *, start_px: float = 100.0, end_px: float = 100.0,
              n: int = 30, spread_bps: float = 10.0, span_seconds: int = 290):
        now = datetime.now(timezone.utc)
        step = (end_px - start_px) / max(n - 1, 1)
        dt = span_seconds / max(n - 1, 1)
        for i in range(n):
            ts = (now - timedelta(seconds=(n - 1 - i) * dt)).isoformat()
            px = start_px + step * i
            half = px * spread_bps / 2 / 10_000
            execute(
                "INSERT INTO tick(instrument_id, ts, bid, ask, last, trade_size) "
                "VALUES(?,?,?,?,?,?)",
                (iid, ts, px - half, px + half, px, 1000),
            )

    return _seed


@pytest.fixture
def watch_row():
    """Fetch a watch row in the shape rules.evaluate() expects."""
    from server.db import one

    def _get(watch_id: int) -> dict:
        return one(
            "SELECT w.id, w.instrument_id, w.direction, w.px_jump_pct, "
            "       w.px_jump_window_s, w.spread_bps_max, w.volume_zscore, i.symbol "
            "FROM watch w JOIN instrument i ON i.id=w.instrument_id WHERE w.id=?",
            (watch_id,),
        )

    return _get


@pytest.fixture
def fake_socketio():
    """Records every (event, payload) for engine-broadcast assertions."""
    class _Fake:
        def __init__(self) -> None:
            self.emissions: list[tuple[str, dict]] = []

        def emit(self, event: str, payload: dict) -> None:
            self.emissions.append((event, payload))

    return _Fake()


# -------------------- Phase 2 fixtures --------------------


@pytest.fixture
def make_watch_with_profile(make_watch):
    """Like make_watch, but also persists a meta_json + FinBERT profile_embedding.

    Returns (instrument_id, watch_id). Uses the deterministic stub FinBERT, so
    the embedding is content-keyed and stable across test runs.
    """
    import json

    from server.db import execute
    from server.nlp.finbert import embedding_to_blob, get_finbert

    def _mk(symbol: str, direction: str = "BULL", *,
            sector: str = "Technology", industry: str = "Software",
            country: str = "US",
            profile_text: str = "Tech company exposed to rates and tariffs."):
        iid, wid = make_watch(symbol, direction)
        meta = {"sector": sector, "industry": industry, "country": country,
                "description": profile_text}
        emb = get_finbert().score(profile_text).embedding
        execute(
            "UPDATE instrument SET meta_json=?, meta_refreshed_at=CURRENT_TIMESTAMP, "
            "profile_text=?, profile_embedding=? WHERE id=?",
            (json.dumps(meta), profile_text, embedding_to_blob(emb), iid),
        )
        return iid, wid

    return _mk


@pytest.fixture
def seed_news():
    """Insert a news row; returns its id. Defaults to a high-relevance adverse hit."""
    import json as _json
    from datetime import datetime, timezone

    from server.db import execute

    def _mk(*, title: str = "AAPL plunges on regulatory probe",
            snippet: str = "regulators announce investigation into AAPL",
            tickers: list[str] | None = None,
            relevance: float = 0.96,
            relevance_source: str = "symbol",
            sentiment: float = -0.85,
            sentiment_label: str = "negative",
            sentiment_conf: float = 0.93,
            url: str | None = None,
            massive_id: str | None = None,
            published_at: str | None = None):
        now = datetime.now(timezone.utc).isoformat()
        cur = execute(
            "INSERT INTO news(fetched_at, source, url, title, snippet, published_at, "
            "massive_id, relevance, relevance_source, sentiment, sentiment_label, "
            "sentiment_conf, tickers_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now, "StubWire",
             url or f"https://example.com/{abs(hash(title))}",
             title, snippet, published_at or now,
             massive_id or f"stub-{abs(hash(title))}",
             relevance, relevance_source, sentiment, sentiment_label,
             sentiment_conf, _json.dumps(tickers or ["AAPL"])),
        )
        return cur.lastrowid

    return _mk


@pytest.fixture
def seed_social_post():
    """Insert a social_post row; returns its id. Inserts the X account if missing."""
    import json as _json
    from datetime import datetime, timezone

    from server.db import execute, one

    def _mk(*, handle: str = "SecTreasury",
            body: str = "Announcing new tariffs affecting $AAPL imports",
            tickers: list[str] | None = None,
            relevance: float = 0.9,
            relevance_source: str = "symbol",
            sentiment: float = -0.7,
            sentiment_label: str = "negative",
            sentiment_conf: float = 0.88):
        acct = one("SELECT id FROM social_account_watch WHERE handle=?", (handle,))
        if acct is None:
            cur = execute(
                "INSERT INTO social_account_watch(source, handle, label) "
                "VALUES('x',?,?)", (handle, handle),
            )
            account_id = cur.lastrowid
        else:
            account_id = acct["id"]
        now = datetime.now(timezone.utc).isoformat()
        cur = execute(
            "INSERT INTO social_post(source, account_id, external_post_id, posted_at, "
            "fetched_at, body, url, tickers_json, relevance, relevance_source, "
            "sentiment, sentiment_label, sentiment_conf) "
            "VALUES('x',?,?,?,?,?,?,?,?,?,?,?,?)",
            (account_id, f"stub-{abs(hash(body))}", now, now, body,
             f"https://x.com/{handle}/status/{abs(hash(body))}",
             _json.dumps(tickers or ["AAPL"]),
             relevance, relevance_source, sentiment, sentiment_label, sentiment_conf),
        )
        return cur.lastrowid

    return _mk
