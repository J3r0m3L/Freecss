"""Massive (Polygon, post-rebrand) adapter — real-time L1 quotes + trades over
WebSocket and 1m aggregate bars over REST (DESIGN.md §3.1, §5, §13).

Legacy `polygon.io` endpoints are still in use post-rebrand; MASSIVE_API_KEY
(or the POLYGON_API_KEY alias) authenticates both. $199/mo flat — no per-call
billing, so this adapter writes no api_cost_event rows.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import requests
import websocket  # websocket-client

from server.adapters.base import Bar, OnTick, Quote

log = logging.getLogger("deleveraging_watch.massive")

_WS_URL = "wss://socket.polygon.io/stocks"
_REST_BASE = "https://api.polygon.io"


def _api_key() -> str:
    key = os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY")
    if not key:
        raise RuntimeError(
            "MASSIVE_API_KEY (or POLYGON_API_KEY) is required for the massive adapter"
        )
    return key


class MassiveAdapter:
    name = "massive"

    def __init__(self) -> None:
        self._key = _api_key()
        self._on_tick: OnTick | None = None
        self._symbols: set[str] = set()
        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._authed = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        # Latest half-quote / last-trade per symbol, merged into each emitted Quote.
        self._book: dict[str, dict] = {}
        self.last_msg_at: float = 0.0

    # --- public API (DataAdapter protocol) ---

    def subscribe_quotes(self, symbols: list[str], on_tick: OnTick) -> None:
        self._on_tick = on_tick
        with self._lock:
            self._symbols.update(symbols)
        if self._thread is None:
            self._thread = threading.Thread(target=self._run_forever, name="massive-ws",
                                            daemon=True)
            self._thread.start()
        elif self._authed.is_set():
            self._send_subscribe(symbols)

    def get_bars(self, symbol: str, tf: str, since: datetime) -> list[Bar]:
        if tf != "1m":
            raise ValueError(f"massive adapter Phase 1 serves tf=1m only, got {tf!r}")
        frm = since.astimezone(timezone.utc).strftime("%Y-%m-%d")
        to = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        url = (f"{_REST_BASE}/v2/aggs/ticker/{symbol}/range/1/minute/{frm}/{to}"
               f"?adjusted=true&sort=asc&limit=50000&apiKey={self._key}")
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        out: list[Bar] = []
        for r in resp.json().get("results", []) or []:
            ts = datetime.fromtimestamp(r["t"] / 1000, tz=timezone.utc)
            if ts < since:
                continue
            out.append(Bar(symbol, ts, r["o"], r["h"], r["l"], r["c"],
                           int(r.get("v", 0)), r.get("vw")))
        return out

    def supports(self, asset_class: str) -> bool:
        return asset_class in {"equity", "etf", "index"}

    def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass

    def is_healthy(self) -> bool:
        """True if authed and we've seen a message recently (quote_stream_supervisor)."""
        return self._authed.is_set() and (time.time() - self.last_msg_at) < 60

    # --- internals ---

    def _run_forever(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            self._authed.clear()
            self._ws = websocket.WebSocketApp(
                _WS_URL,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=lambda _ws, err: log.warning("massive ws error: %s", err),
                on_close=lambda _ws, *_: log.info("massive ws closed"),
            )
            try:
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception:  # noqa: BLE001
                log.exception("massive ws run_forever crashed")
            if self._stop.is_set():
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)  # exponential backoff, capped (§10.3 / §14)

    def _on_open(self, ws) -> None:
        ws.send(json.dumps({"action": "auth", "params": self._key}))

    def _send_subscribe(self, symbols: list[str]) -> None:
        if not symbols or self._ws is None:
            return
        params = ",".join(f"Q.{s}" for s in symbols) + "," + ",".join(f"T.{s}" for s in symbols)
        self._ws.send(json.dumps({"action": "subscribe", "params": params}))

    def _on_message(self, _ws, raw: str) -> None:
        self.last_msg_at = time.time()
        try:
            events = json.loads(raw)
        except json.JSONDecodeError:
            return
        for ev in events:
            kind = ev.get("ev")
            if kind == "status":
                if ev.get("status") == "auth_success":
                    self._authed.set()
                    with self._lock:
                        self._send_subscribe(sorted(self._symbols))
                    log.info("massive ws authenticated; subscribed %d symbols",
                             len(self._symbols))
                continue
            if kind == "Q":
                self._handle_quote(ev)
            elif kind == "T":
                self._handle_trade(ev)

    def _handle_quote(self, ev: dict) -> None:
        sym = ev.get("sym")
        if not sym:
            return
        b = self._book.setdefault(sym, {})
        b["bid"], b["ask"] = ev.get("bp"), ev.get("ap")
        b["bid_size"], b["ask_size"] = ev.get("bs"), ev.get("as")
        b["ts"] = ev.get("t")
        self._emit(sym)

    def _handle_trade(self, ev: dict) -> None:
        sym = ev.get("sym")
        if not sym:
            return
        b = self._book.setdefault(sym, {})
        b["last"], b["trade_size"] = ev.get("p"), ev.get("s")
        b["ts"] = ev.get("t")
        self._emit(sym)

    def _emit(self, sym: str) -> None:
        if self._on_tick is None:
            return
        b = self._book[sym]
        ts_ms = b.get("ts")
        ts = (datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
              if ts_ms else datetime.now(timezone.utc))
        self._on_tick(Quote(
            symbol=sym, ts=ts,
            bid=b.get("bid"), ask=b.get("ask"), last=b.get("last"),
            bid_size=b.get("bid_size"), ask_size=b.get("ask_size"),
            trade_size=b.get("trade_size"),
        ))
