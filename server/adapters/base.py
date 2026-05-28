"""Adapter contract (DESIGN.md §13). All asset classes route through this seam."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol, runtime_checkable


@dataclass(frozen=True)
class Quote:
    symbol: str
    ts: datetime
    bid: float | None
    ask: float | None
    last: float | None
    bid_size: int | None = None
    ask_size: int | None = None
    trade_size: int | None = None


@dataclass(frozen=True)
class Bar:
    symbol: str
    ts: datetime
    o: float
    h: float
    l: float
    c: float
    v: int
    vwap: float | None = None


OnTick = Callable[[Quote], None]


@runtime_checkable
class DataAdapter(Protocol):
    name: str

    def subscribe_quotes(self, symbols: list[str], on_tick: OnTick) -> None: ...
    def get_bars(self, symbol: str, tf: str, since: datetime) -> list[Bar]: ...
    def supports(self, asset_class: str) -> bool: ...
    def stop(self) -> None: ...
