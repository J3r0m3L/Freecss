"""Liquidity analytics — ADV roll-up + exit-liquidity helpers (DESIGN.md §11.C)."""
import math
from datetime import date, datetime, timedelta, timezone

from server.analytics.liquidity import (
    compute_daily_snapshot,
    exit_liquidity,
    liquidity_rank,
)
from server.db import execute


def _seed_daily(iid: int, n: int = 25, *, close: float = 100.0, volume: int = 1_000_000):
    today = date.today()
    for i in range(n):
        d = (today - timedelta(days=(n - i))).isoformat()
        execute("INSERT OR REPLACE INTO bar_daily(instrument_id, date, o, h, l, c, v) "
                "VALUES(?,?,?,?,?,?,?)",
                (iid, d, close, close, close, close, volume))


def _seed_today_tick(iid: int, *, bid: float, ask: float, last: float):
    ts = datetime.now(timezone.utc).replace(hour=14).isoformat()
    execute("INSERT INTO tick(instrument_id, ts, bid, ask, last) VALUES(?,?,?,?,?)",
            (iid, ts, bid, ask, last))


def _seed_today_bar_1m(iid: int, *, volume: int = 1000):
    ts = datetime.now(timezone.utc).replace(hour=14, minute=0,
                                            second=0, microsecond=0).isoformat()
    execute("INSERT INTO bar_1m(instrument_id, ts, o, h, l, c, v) "
            "VALUES(?,?,?,?,?,?,?)",
            (iid, ts, 100, 100, 100, 100, volume))


def test_empty_returns_all_none(make_watch):
    iid, _ = make_watch("X")
    snap = compute_daily_snapshot(iid)
    assert snap.is_empty()
    assert snap.days_used == 0


def test_adv_averages_last_21_days(make_watch):
    iid, _ = make_watch("X")
    _seed_daily(iid, n=25, close=100.0, volume=2_000_000)
    snap = compute_daily_snapshot(iid)
    assert snap.adv_shares_21d == 2_000_000
    assert snap.adv_dollar_21d == 200_000_000
    assert snap.days_used == 21


def test_spread_avg_bps_from_ticks(make_watch):
    iid, _ = make_watch("X")
    _seed_daily(iid)
    # Two ticks today, both ~10 bps spread.
    _seed_today_tick(iid, bid=99.95, ask=100.05, last=100.0)   # 10 bps
    snap = compute_daily_snapshot(iid)
    assert snap.spread_avg_bps is not None
    assert abs(snap.spread_avg_bps - 10.0) < 0.5


def test_pct_zero_volume_flag(make_watch):
    iid, _ = make_watch("X")
    _seed_daily(iid)
    # Two zero-volume bars + one non-zero today.
    ts0 = datetime.now(timezone.utc).replace(hour=10).isoformat()
    ts1 = datetime.now(timezone.utc).replace(hour=11).isoformat()
    ts2 = datetime.now(timezone.utc).replace(hour=12).isoformat()
    for ts, v in [(ts0, 0), (ts1, 0), (ts2, 1000)]:
        execute("INSERT INTO bar_1m(instrument_id, ts, o, h, l, c, v) "
                "VALUES(?,?,?,?,?,?,?)", (iid, ts, 100, 100, 100, 100, v))
    snap = compute_daily_snapshot(iid)
    assert abs(snap.pct_zero_volume - (2 / 3)) < 1e-9


def test_exit_liquidity_basic():
    # 500k shares / (0.10 × 1M ADV) = 5 days
    # cost ≈ 50 bps × sqrt(0.5) ≈ 35.36
    r = exit_liquidity(position_size=500_000, adv_shares=1_000_000,
                       spread_bps=50.0, participation=0.10)
    assert abs(r.days_to_exit - 5.0) < 1e-9
    assert abs(r.cost_to_exit_bps - 50.0 * math.sqrt(0.5)) < 1e-9


def test_exit_liquidity_no_position():
    r = exit_liquidity(position_size=None, adv_shares=1_000_000, spread_bps=50.0)
    assert r.days_to_exit is None and r.cost_to_exit_bps is None


def test_exit_liquidity_no_adv():
    r = exit_liquidity(position_size=1000, adv_shares=None, spread_bps=50.0)
    assert r.days_to_exit is None and r.cost_to_exit_bps is None


def test_exit_liquidity_missing_spread_keeps_days():
    """No spread known → still report days_to_exit; only cost is None."""
    r = exit_liquidity(position_size=1000, adv_shares=10_000, spread_bps=None)
    assert r.days_to_exit is not None
    assert r.cost_to_exit_bps is None


def test_liquidity_rank_picks_correct_position(make_watch):
    a, _ = make_watch("AA")
    b, _ = make_watch("BB")
    c, _ = make_watch("CC")
    now = datetime.now(timezone.utc).isoformat()
    for iid, adv in [(a, 1_000_000), (b, 5_000_000), (c, 3_000_000)]:
        execute(
            "INSERT INTO liquidity_daily(instrument_id, date, adv_shares_21d, "
            "adv_dollar_21d, computed_at) VALUES(?,?,?,?,?)",
            (iid, date.today().isoformat(), adv, adv * 100, now),
        )
    # B is biggest → rank 1; C → 2; A → 3 of 3.
    assert liquidity_rank(b) == (1, 3)
    assert liquidity_rank(c) == (2, 3)
    assert liquidity_rank(a) == (3, 3)


def test_liquidity_rank_none_when_no_snapshot(make_watch):
    iid, _ = make_watch("ORPHAN")
    assert liquidity_rank(iid) is None
