"""Phase 0 stub adapter: synthetic random-walk quotes so the grid has something
to render before the live Massive feed lands in Phase 1. No network, no keys."""
from __future__ import annotations

import random
import threading
import time
from datetime import datetime, timedelta, timezone

from server.adapters.base import Bar, OnTick, Quote


class StubAdapter:
    name = "stub"

    def __init__(self, tick_interval_s: float = 2.0) -> None:
        self._interval = tick_interval_s
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._prices: dict[str, float] = {}

    def _seed_price(self, symbol: str) -> float:
        if symbol not in self._prices:
            # Deterministic-ish starting price per symbol so restarts look stable.
            self._prices[symbol] = 50.0 + (hash(symbol) % 400)
        return self._prices[symbol]

    def subscribe_quotes(self, symbols: list[str], on_tick: OnTick) -> None:
        for s in symbols:
            self._seed_price(s)

        def loop() -> None:
            while not self._stop.is_set():
                for sym in list(self._prices):
                    px = self._prices[sym]
                    px = max(0.5, px * (1 + random.gauss(0, 0.001)))
                    self._prices[sym] = px
                    spread = px * random.uniform(0.0002, 0.0010)
                    on_tick(
                        Quote(
                            symbol=sym,
                            ts=datetime.now(timezone.utc),
                            bid=round(px - spread / 2, 4),
                            ask=round(px + spread / 2, 4),
                            last=round(px, 4),
                            bid_size=random.randint(1, 50) * 100,
                            ask_size=random.randint(1, 50) * 100,
                            trade_size=random.randint(1, 20) * 100,
                        )
                    )
                self._stop.wait(self._interval)

        self._thread = threading.Thread(target=loop, name="stub-quotes", daemon=True)
        self._thread.start()

    def get_bars(self, symbol: str, tf: str, since: datetime) -> list[Bar]:
        """Synthetic 1m bars walking back from now to `since`."""
        px = self._seed_price(symbol)
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        bars: list[Bar] = []
        t = since.replace(second=0, microsecond=0)
        p = px * 0.97
        while t <= now:
            o = p
            c = max(0.5, o * (1 + random.gauss(0, 0.002)))
            h = max(o, c) * (1 + random.uniform(0, 0.001))
            low = min(o, c) * (1 - random.uniform(0, 0.001))
            v = random.randint(1_000, 100_000)
            bars.append(Bar(symbol, t, round(o, 4), round(h, 4), round(low, 4), round(c, 4), v,
                            round((h + low + c) / 3, 4)))
            p = c
            t += timedelta(minutes=1)
        return bars

    def supports(self, asset_class: str) -> bool:
        return asset_class in {"equity", "etf", "index"}

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self._interval + 1)
