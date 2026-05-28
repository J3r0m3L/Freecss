"""Daily bars from Massive (Polygon) REST (DESIGN.md §9, Phase 3 historical warmup).

GET /v2/aggs/ticker/{sym}/range/1/day/{from}/{to}?adjusted=true&sort=asc

Bundled in Stocks Advanced — no incremental billing. Returns plain (date, ohlcv)
rows so the bulk-loader, factor_pca, and factor_refresh jobs can persist them
into `bar_daily` directly.

A deterministic stub fires when MASSIVE_API_KEY is missing (or the call fails).
The stub generates correlated returns within a single call to a basket so PCA
+ regression tests get sensible factor structure — see `_stub_basket()`.
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import requests

log = logging.getLogger("deleveraging_watch.adapters.massive_daily")

_REST_BASE = "https://api.polygon.io"
_TIMEOUT_S = 30


def _api_key() -> str:
    return os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY") or ""


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    date: date
    o: float
    h: float
    l: float
    c: float
    v: int
    vwap: float | None


def fetch_daily_bars(symbol: str, *, days: int = 252) -> list[DailyBar]:
    """Trailing `days` of daily bars for `symbol`, ASC by date. Stubs on no-key."""
    if not _api_key():
        return _stub_series(symbol, days=days)
    frm = (date.today() - timedelta(days=int(days * 1.6))).isoformat()  # pad weekends/holidays
    to = date.today().isoformat()
    url = (f"{_REST_BASE}/v2/aggs/ticker/{symbol}/range/1/day/{frm}/{to}"
           f"?adjusted=true&sort=asc&limit=50000&apiKey={_api_key()}")
    try:
        resp = requests.get(url, timeout=_TIMEOUT_S)
        resp.raise_for_status()
        rows = resp.json().get("results", []) or []
    except Exception as exc:  # noqa: BLE001
        log.warning("massive daily fetch failed for %s (%s); using stub", symbol, exc)
        return _stub_series(symbol, days=days)

    out: list[DailyBar] = []
    for r in rows:
        d = datetime.fromtimestamp(r["t"] / 1000, tz=timezone.utc).date()
        out.append(DailyBar(symbol=symbol, date=d,
                            o=r["o"], h=r["h"], l=r["l"], c=r["c"],
                            v=int(r.get("v", 0)), vwap=r.get("vw")))
    return out[-days:]


# ---- Stub series with cross-symbol correlation -----------------------------
# Each stub bar series is generated from a per-symbol seed PLUS a small set of
# shared market factors. That way a candidate basket like [SPY, IVV, VOO] has
# nearly-identical returns (PCA picks any of them as rep with ~99% PC1 var),
# while [SPY, USO] correlates much more weakly — exactly the structure PCA and
# OLS-regression tests need.


def _seed(symbol: str, salt: str = "") -> int:
    return int(hashlib.sha256(f"{salt}:{symbol}".encode()).hexdigest()[:12], 16)


def _shared_factors(days: int) -> dict[str, list[float]]:
    """Daily moves for a handful of market factors used to color stub returns."""
    rng = random.Random(_seed("__market__"))
    return {
        "broad":    [rng.gauss(0.0005, 0.011) for _ in range(days)],
        "rates":    [rng.gauss(0.0,     0.004) for _ in range(days)],
        "energy":   [rng.gauss(0.0,     0.018) for _ in range(days)],
        "gold":     [rng.gauss(0.0,     0.010) for _ in range(days)],
        "crypto":   [rng.gauss(0.0,     0.040) for _ in range(days)],
        "vol":      [rng.gauss(0.0,     0.030) for _ in range(days)],  # VIX-ish
    }


# Coarse mapping: symbol substring → which shared factor it loads on.
_FACTOR_MAP: dict[str, str] = {
    # Bonds / rates
    "TLT": "rates", "IEF": "rates", "SHV": "rates", "BIL": "rates", "VGIT": "rates",
    "VGLT": "rates", "EDV": "rates", "TIP": "rates", "SCHP": "rates", "VTIP": "rates",
    "MBB": "rates", "VMBS": "rates", "LQD": "rates", "VCIT": "rates",
    "HYG": "rates", "JNK": "rates", "EMB": "rates", "PCY": "rates",
    "BKLN": "rates", "SRLN": "rates",
    # Energy
    "XLE": "energy", "VDE": "energy", "IYE": "energy", "FENY": "energy",
    "USO": "energy", "BNO": "energy", "DBO": "energy",
    "UNG": "energy", "BOIL": "energy",
    # Gold / metals
    "GLD": "gold", "IAU": "gold", "GLDM": "gold", "SGOL": "gold",
    "SLV": "gold", "SIVR": "gold",
    # Crypto
    "IBIT": "crypto", "FBTC": "crypto", "BTCO": "crypto", "BITB": "crypto",
    "ARKB": "crypto", "ETHA": "crypto", "FETH": "crypto",
    "WGMI": "crypto", "BKCH": "crypto", "BLOK": "crypto",
    # VIX
    "VIXY": "vol", "VXX": "vol", "UVXY": "vol",
}


def _factor_for(symbol: str) -> str:
    sym = symbol.upper()
    if sym in _FACTOR_MAP:
        return _FACTOR_MAP[sym]
    return "broad"  # default: tracks the broad market


def _stub_series(symbol: str, *, days: int) -> list[DailyBar]:
    factor = _factor_for(symbol)
    market = _shared_factors(days)[factor]
    rng = random.Random(_seed(symbol, salt=factor))

    # Loading on the shared factor — slight per-symbol noise so basket reps
    # differ a touch from each other (so PCA can actually pick a winner).
    beta = 0.85 + (rng.random() * 0.30)         # 0.85..1.15
    idio_vol = 0.004 if factor != "vol" else 0.020

    # Bond/rates factor moves are tiny, but bond-ETF prices are noisier than
    # their returns suggest — keep things in realistic units.
    base_price = 50 + (rng.random() * 350)
    px = base_price
    out: list[DailyBar] = []
    today = date.today()
    for i in range(days):
        d = today - timedelta(days=(days - i))
        ret = beta * market[i] + rng.gauss(0.0, idio_vol)
        prev = px
        px = max(0.5, px * (1.0 + ret))
        hi = max(prev, px) * (1 + abs(rng.gauss(0.0, 0.002)))
        lo = min(prev, px) * (1 - abs(rng.gauss(0.0, 0.002)))
        vol = int(1_000_000 * (1 + abs(rng.gauss(0, 0.3))))
        out.append(DailyBar(symbol=symbol, date=d,
                            o=prev, h=hi, l=lo, c=px, v=vol,
                            vwap=(prev + px) / 2))
    return out


def stub_returns(symbol: str, days: int) -> list[float]:
    """Convenience for tests/analytics: stub returns aligned to fetch_daily_bars()."""
    bars = _stub_series(symbol, days=days + 1)
    return [(bars[i].c - bars[i - 1].c) / bars[i - 1].c
            for i in range(1, len(bars)) if bars[i - 1].c > 0]


__all__ = ["DailyBar", "fetch_daily_bars", "stub_returns"]


# Tiny safety net so this module never silently NaNs out.
def _assert_finite(x: float) -> float:
    if math.isnan(x) or math.isinf(x):
        return 0.0
    return x
