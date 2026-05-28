"""Intraday residual (DESIGN.md §9)."""
from datetime import date, datetime, timedelta, timezone

from server.analytics.residual import latest_intraday_move, residual
from server.db import execute


def _seed_prev_close(iid: int, px: float) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    execute(
        "INSERT OR REPLACE INTO bar_daily(instrument_id, date, o, h, l, c, v) "
        "VALUES(?,?,?,?,?,?,?)",
        (iid, yesterday, px, px, px, px, 1_000_000),
    )


def _seed_latest_1m(iid: int, px: float) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    execute(
        "INSERT OR REPLACE INTO bar_1m(instrument_id, ts, o, h, l, c, v) "
        "VALUES(?,?,?,?,?,?,?)",
        (iid, ts, px, px, px, px, 10_000),
    )


def test_no_data_returns_none(make_watch):
    iid, _ = make_watch("X")
    m = latest_intraday_move(iid)
    assert m.return_pct is None


def test_intraday_return_basic(make_watch):
    iid, _ = make_watch("X")
    _seed_prev_close(iid, 100.0)
    _seed_latest_1m(iid, 102.0)
    m = latest_intraday_move(iid)
    assert abs(m.return_pct - 0.02) < 1e-9


def test_residual_subtracts_expected(make_watch):
    """Residual = actual − (α + β · r_rep). With α=0, β=2, rep up 1%, watch
    up 1.5% → expected 2%, residual −0.5%."""
    iid_w, _ = make_watch("W")
    iid_r, _ = make_watch("R")
    _seed_prev_close(iid_w, 100.0)
    _seed_prev_close(iid_r, 200.0)
    _seed_latest_1m(iid_w, 101.5)   # +1.5%
    _seed_latest_1m(iid_r, 202.0)   # +1.0%
    res = residual(alpha=0.0, beta=2.0, watch_id=iid_w, rep_id=iid_r)
    assert abs(res - (-0.005)) < 1e-9


def test_residual_none_when_data_missing(make_watch):
    iid_w, _ = make_watch("W")
    iid_r, _ = make_watch("R")
    _seed_prev_close(iid_w, 100.0)
    # Rep has no prev close → return_pct is None → residual is None.
    _seed_latest_1m(iid_w, 101.0)
    _seed_latest_1m(iid_r, 200.0)
    assert residual(alpha=0.0, beta=1.0, watch_id=iid_w, rep_id=iid_r) is None


def test_prev_close_zero_guard(make_watch):
    iid, _ = make_watch("Z")
    _seed_prev_close(iid, 0.0)   # pathological
    _seed_latest_1m(iid, 10.0)
    assert latest_intraday_move(iid).return_pct is None
