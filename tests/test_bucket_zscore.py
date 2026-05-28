"""Bucket-level intraday z-score (DESIGN.md §9, Phase 5)."""
from datetime import date, datetime, timedelta, timezone

from server.analytics.bucket_zscore import MIN_OBS, bucket_zscore
from server.db import execute


def _seed_daily_close(iid: int, *, days_back: int, close: float) -> None:
    d = (date.today() - timedelta(days=days_back)).isoformat()
    execute("INSERT OR REPLACE INTO bar_daily(instrument_id, date, o, h, l, c, v) "
            "VALUES(?,?,?,?,?,?,?)",
            (iid, d, close, close, close, close, 1_000_000))


def _seed_baseline(iid: int, *, prices: list[float]) -> None:
    """Write a sequence of historical daily closes ending yesterday."""
    n = len(prices)
    for i, p in enumerate(prices):
        _seed_daily_close(iid, days_back=(n - i), close=p)


def _seed_today_intraday(iid: int, *, last: float) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    execute("INSERT INTO bar_1m(instrument_id, ts, o, h, l, c, v) "
            "VALUES(?,?,?,?,?,?,?)",
            (iid, ts, last, last, last, last, 10_000))


def test_no_intraday_returns_none(make_watch):
    iid, _ = make_watch("X")
    _seed_baseline(iid, prices=[100 + 0.1 * i for i in range(30)])
    assert bucket_zscore(iid) is None


def test_insufficient_history_returns_none(make_watch):
    iid, _ = make_watch("X")
    _seed_baseline(iid, prices=[100, 100.5, 101])  # < MIN_OBS
    _seed_today_intraday(iid, last=102)
    assert bucket_zscore(iid) is None


def test_zero_std_returns_none(make_watch):
    iid, _ = make_watch("X")
    _seed_baseline(iid, prices=[100.0] * (MIN_OBS + 5))  # flat → zero std
    _seed_today_intraday(iid, last=101)
    assert bucket_zscore(iid) is None


def test_large_positive_intraday_move_yields_high_z(make_watch):
    iid, _ = make_watch("X")
    # 30 days of tiny ±0.001 returns: baseline std is small.
    base = [100.0]
    for i in range(MIN_OBS + 10):
        base.append(base[-1] * (1 + (0.001 if i % 2 == 0 else -0.001)))
    _seed_baseline(iid, prices=base)
    # Today's intraday: +5% — should land at very high z.
    last_baseline_close = base[-1]
    _seed_today_intraday(iid, last=last_baseline_close * 1.05)
    res = bucket_zscore(iid)
    assert res is not None
    assert res.z > 10
    assert res.today_return > 0.04


def test_negative_move_returns_negative_z(make_watch):
    iid, _ = make_watch("X")
    base = [100.0]
    for i in range(MIN_OBS + 10):
        base.append(base[-1] * (1 + (0.001 if i % 2 == 0 else -0.001)))
    _seed_baseline(iid, prices=base)
    _seed_today_intraday(iid, last=base[-1] * 0.95)
    res = bucket_zscore(iid)
    assert res is not None
    assert res.z < -10
