"""StubAdapter (DESIGN.md §13) — Phase 0 synthetic feed used until Massive lands."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from server.adapters.base import Quote
from server.adapters.stub import StubAdapter


def test_subscribe_delivers_ticks_for_each_symbol():
    got: list[Quote] = []
    event = threading.Event()

    def on_tick(q: Quote) -> None:
        got.append(q)
        if {q.symbol for q in got} >= {"AAA", "BBB"}:
            event.set()

    a = StubAdapter(tick_interval_s=0.05)
    a.subscribe_quotes(["AAA", "BBB"], on_tick)
    try:
        assert event.wait(timeout=2.0), "no ticks delivered within 2s"
    finally:
        a.stop()

    assert {q.symbol for q in got} == {"AAA", "BBB"}
    # Quote integrity: bid <= last <= ask (within float tolerance).
    for q in got[:10]:
        assert q.bid is not None and q.ask is not None and q.last is not None
        assert q.bid <= q.last + 1e-6
        assert q.last <= q.ask + 1e-6


def test_get_bars_returns_minute_grid():
    a = StubAdapter()
    since = datetime.now(timezone.utc) - timedelta(minutes=5)
    bars = a.get_bars("CCC", "1m", since)
    assert len(bars) >= 5
    # Strictly increasing minute timestamps.
    for prev, cur in zip(bars, bars[1:]):
        assert cur.ts > prev.ts
        assert (cur.ts - prev.ts).total_seconds() == 60


def test_supports_equity_and_etf():
    a = StubAdapter()
    assert a.supports("equity")
    assert a.supports("etf")
    assert not a.supports("future")
