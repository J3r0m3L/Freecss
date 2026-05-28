"""Liquidity layer (DESIGN.md §11.C, §16 Phase 4).

Two distinct computations:

1. **Daily roll-up** (`compute_daily_snapshot`) — called by the EOD job. Rolls
   the trailing 21 daily bars into adv_shares_21d / adv_dollar_21d, the session-
   average spread from today's bar_1m rows (when available), and a
   `pct_zero_volume` thin-name flag.

2. **Exit liquidity** (`exit_liquidity`) — pure-function helper consumed by the
   /api/instrument/<sym>/liquidity endpoint. Given a position size, ADV, spread,
   and a participation rate, returns:
     - days_to_exit  = position / (participation × ADV)
     - cost_to_exit_bps ≈ spread × sqrt(position / ADV)

The spread×√(participation) market-impact approximation is the workhorse
Almgren/Chriss-style estimate — adequate for "is this position huge relative to
ADV?" rather than execution-grade slippage modelling, which is out of scope.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from server.db import one, rows


@dataclass(frozen=True)
class DailySnapshot:
    adv_shares_21d: float | None
    adv_dollar_21d: float | None
    spread_avg_bps: float | None
    pct_zero_volume: float | None
    days_used: int                # how many trailing daily rows fed ADV

    def is_empty(self) -> bool:
        return (self.adv_shares_21d is None and self.adv_dollar_21d is None
                and self.spread_avg_bps is None and self.pct_zero_volume is None)


def compute_daily_snapshot(instrument_id: int, *, as_of: date | None = None,
                           window: int = 21) -> DailySnapshot:
    """Roll trailing `window` daily bars + today's bar_1m into a snapshot.

    `as_of` defaults to *today in UTC* to match how the tick/bar_1m tables
    timestamp rows; passing a local-tz date risks a 1-day off-by-one near
    midnight on the machine that runs this.
    """
    as_of = as_of or datetime.now(timezone.utc).date()

    # ADV from bar_daily (closes × volume).
    bars = rows(
        "SELECT date, c, v FROM bar_daily WHERE instrument_id=? AND date < ? "
        "ORDER BY date DESC LIMIT ?",
        (instrument_id, as_of.isoformat(), window),
    )
    if bars:
        shares = [b["v"] for b in bars if b["v"] is not None]
        dollars = [b["c"] * b["v"] for b in bars
                   if b["c"] is not None and b["v"] is not None]
        adv_shares = sum(shares) / len(shares) if shares else None
        adv_dollar = sum(dollars) / len(dollars) if dollars else None
        days_used = len(bars)
    else:
        adv_shares = None
        adv_dollar = None
        days_used = 0

    # Today's intraday microstructure from bar_1m. We use `tick` for spread if
    # available; bar_1m doesn't carry spread directly.
    today_start = datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc).isoformat()
    today_end = (datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc)
                 + timedelta(days=1)).isoformat()

    one_m = rows(
        "SELECT v FROM bar_1m WHERE instrument_id=? AND ts >= ? AND ts < ?",
        (instrument_id, today_start, today_end),
    )
    if one_m:
        zeros = sum(1 for b in one_m if (b["v"] or 0) == 0)
        pct_zero = zeros / len(one_m)
    else:
        pct_zero = None

    tick_spread = one(
        "SELECT AVG((ask - bid) * 10000.0 / NULLIF(last, 0)) bps "
        "FROM tick WHERE instrument_id=? AND ts >= ? AND ts < ? "
        "AND bid IS NOT NULL AND ask IS NOT NULL AND last IS NOT NULL AND last > 0",
        (instrument_id, today_start, today_end),
    )
    spread_bps = (tick_spread or {}).get("bps") if tick_spread else None

    return DailySnapshot(
        adv_shares_21d=adv_shares,
        adv_dollar_21d=adv_dollar,
        spread_avg_bps=spread_bps,
        pct_zero_volume=pct_zero,
        days_used=days_used,
    )


@dataclass(frozen=True)
class ExitLiquidity:
    days_to_exit: float | None
    cost_to_exit_bps: float | None
    participation: float
    position_size: float


def exit_liquidity(*, position_size: float | None, adv_shares: float | None,
                   spread_bps: float | None,
                   participation: float = 0.10) -> ExitLiquidity:
    """Pure function — no DB access. Returns None for either metric if inputs
    are insufficient (e.g. no position set or ADV unknown)."""
    if position_size is None or position_size <= 0:
        return ExitLiquidity(None, None, participation, position_size or 0.0)
    if adv_shares is None or adv_shares <= 0 or participation <= 0:
        return ExitLiquidity(None, None, participation, position_size)
    days = position_size / (participation * adv_shares)
    cost: float | None = None
    if spread_bps is not None and spread_bps >= 0:
        cost = float(spread_bps) * math.sqrt(position_size / adv_shares)
    return ExitLiquidity(days, cost, participation, position_size)


def liquidity_rank(instrument_id: int) -> tuple[int, int] | None:
    """Rank within the active watchlist by adv_dollar_21d (1 = most liquid).

    Returns (rank, n) or None if the instrument has no liquidity_daily row yet.
    """
    me = one(
        "SELECT adv_dollar_21d FROM liquidity_daily WHERE instrument_id=? "
        "ORDER BY date DESC LIMIT 1",
        (instrument_id,),
    )
    if not me or me["adv_dollar_21d"] is None:
        return None
    # Latest row per active-watch instrument.
    peers = rows(
        "SELECT l.instrument_id, l.adv_dollar_21d FROM liquidity_daily l "
        "JOIN ("
        "  SELECT instrument_id, MAX(date) mx FROM liquidity_daily GROUP BY instrument_id"
        ") last ON last.instrument_id=l.instrument_id AND last.mx=l.date "
        "JOIN watch w ON w.instrument_id=l.instrument_id "
        "WHERE w.active=1 AND l.adv_dollar_21d IS NOT NULL"
    )
    if not peers:
        return None
    sorted_peers = sorted(peers, key=lambda r: r["adv_dollar_21d"], reverse=True)
    n = len(sorted_peers)
    for rank, p in enumerate(sorted_peers, start=1):
        if p["instrument_id"] == instrument_id:
            return rank, n
    return None
