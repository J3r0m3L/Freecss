"""In-memory live state: the latest quote per symbol and feed liveness.

Single process, so a module-level dict guarded by a lock is the whole story.
Ticks are also persisted to the `tick` table by the quote handler; this store
is just the hot snapshot the grid and /api/health read without touching disk.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from server.adapters.base import Quote

_lock = threading.Lock()
_latest: dict[str, Quote] = {}


def update(quote: Quote) -> None:
    with _lock:
        _latest[quote.symbol] = quote


def latest(symbol: str) -> Quote | None:
    with _lock:
        return _latest.get(symbol)


def snapshot() -> dict[str, Quote]:
    with _lock:
        return dict(_latest)


def last_tick_age_s() -> float | None:
    """Seconds since the most recent tick across all symbols (feed-health badge)."""
    with _lock:
        if not _latest:
            return None
        newest = max(q.ts for q in _latest.values())
    return (datetime.now(timezone.utc) - newest).total_seconds()
