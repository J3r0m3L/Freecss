"""Quote feed wiring: bridges the data adapter to live state, SocketIO, and the
`tick` table. Phase 0 uses the stub adapter; the seam is identical for Massive.
"""
from __future__ import annotations

import logging
import threading

from server import state
from server.adapters import make_adapter
from server.adapters.base import Quote
from server.db import get_db, rows

log = logging.getLogger("deleveraging_watch.feed")


class Feed:
    def __init__(self) -> None:
        self._adapter = make_adapter()
        self._socketio = None
        self.adapter = self._adapter  # public handle for supervisor/health checks
        self._symbols: set[str] = set()
        self._inst_ids: dict[str, int] = {}
        self._lock = threading.Lock()

    def _on_tick(self, q: Quote) -> None:
        state.update(q)
        if self._socketio is not None:
            self._socketio.emit(
                f"tick:{q.symbol}",
                {
                    "symbol": q.symbol,
                    "ts": q.ts.isoformat(),
                    "bid": q.bid,
                    "ask": q.ask,
                    "last": q.last,
                    "bid_size": q.bid_size,
                    "ask_size": q.ask_size,
                },
            )
        self._persist(q)

    def _persist(self, q: Quote) -> None:
        inst_id = self._inst_ids.get(q.symbol)
        if inst_id is None:
            return
        try:
            db = get_db()
            db.execute(
                "INSERT OR REPLACE INTO tick"
                "(instrument_id, ts, bid, ask, last, bid_size, ask_size, trade_size) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (inst_id, q.ts.isoformat(), q.bid, q.ask, q.last,
                 q.bid_size, q.ask_size, q.trade_size),
            )
            db.commit()
        except Exception:  # noqa: BLE001 — never let a tick write kill the feed
            log.exception("failed to persist tick for %s", q.symbol)

    def start(self, socketio) -> None:
        self._socketio = socketio
        for r in rows(
            "SELECT i.symbol, i.id FROM watch w JOIN instrument i ON i.id=w.instrument_id "
            "WHERE w.active=1"
        ):
            self._symbols.add(r["symbol"])
            self._inst_ids[r["symbol"]] = r["id"]
        log.info("starting feed (%s) for %d symbols", self._adapter.name, len(self._symbols))
        self._adapter.subscribe_quotes(sorted(self._symbols), self._on_tick)

    def ensure_symbol(self, symbol: str, instrument_id: int) -> None:
        """Begin streaming a newly-added watch symbol without a restart."""
        with self._lock:
            self._inst_ids[symbol] = instrument_id
            if symbol in self._symbols:
                return
            self._symbols.add(symbol)
            self._adapter.subscribe_quotes([symbol], self._on_tick)

    def stop(self) -> None:
        self._adapter.stop()


feed = Feed()
