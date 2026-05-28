"""/api/instrument/<sym>/liquidity (DESIGN.md §7.1, §11.C)."""
import math
from datetime import date, datetime, timezone

from server.db import execute


def _seed_snapshot(iid: int, *, adv_shares: float, spread_bps: float):
    execute(
        "INSERT OR REPLACE INTO liquidity_daily(instrument_id, date, "
        "adv_shares_21d, adv_dollar_21d, spread_avg_bps, pct_zero_volume, "
        "computed_at) VALUES(?,?,?,?,?,?,?)",
        (iid, date.today().isoformat(), adv_shares, adv_shares * 100,
         spread_bps, 0.05, datetime.now(timezone.utc).isoformat()),
    )


def test_unknown_symbol_404(client):
    assert client.get("/api/instrument/ZZZZ/liquidity").status_code == 404


def test_returns_snapshot_fields(client, make_watch):
    iid, wid = make_watch("AAPL")
    _seed_snapshot(iid, adv_shares=1_000_000, spread_bps=12.0)
    body = client.get("/api/instrument/AAPL/liquidity").json
    assert body["symbol"] == "AAPL"
    assert body["adv_shares_21d"] == 1_000_000
    assert body["adv_dollar_21d"] == 100_000_000
    assert body["spread_avg_bps"] == 12.0


def test_no_snapshot_returns_nulls(client, make_watch):
    make_watch("AAPL")
    body = client.get("/api/instrument/AAPL/liquidity").json
    assert body["adv_shares_21d"] is None
    assert body["computed_at"] is None


def test_exit_liquidity_only_when_position_size_set(client, make_watch):
    iid, wid = make_watch("AAPL")
    _seed_snapshot(iid, adv_shares=2_000_000, spread_bps=20.0)
    body = client.get("/api/instrument/AAPL/liquidity").json
    assert body["days_to_exit"] is None and body["cost_to_exit_bps"] is None

    # Set position via the watchlist PATCH endpoint.
    client.patch(f"/api/watchlist/{wid}",
                 json={"thresholds": {"position_size": 100_000}})
    body = client.get("/api/instrument/AAPL/liquidity").json
    # 100k / (0.10 * 2M) = 0.5 days; cost = 20 * sqrt(0.05) ≈ 4.47 bps
    assert abs(body["days_to_exit"] - 0.5) < 1e-9
    assert abs(body["cost_to_exit_bps"] - 20.0 * math.sqrt(0.05)) < 1e-6


def test_participation_param(client, make_watch):
    iid, wid = make_watch("AAPL")
    _seed_snapshot(iid, adv_shares=1_000_000, spread_bps=20.0)
    client.patch(f"/api/watchlist/{wid}",
                 json={"thresholds": {"position_size": 100_000}})
    # 20% participation → days halved.
    body = client.get("/api/instrument/AAPL/liquidity?participation=0.20").json
    assert abs(body["days_to_exit"] - 0.5) < 1e-9


def test_watchlist_rank_returned(client, make_watch):
    iid_a, _ = make_watch("AAA")
    iid_b, _ = make_watch("BBB")
    _seed_snapshot(iid_a, adv_shares=500_000, spread_bps=10.0)
    _seed_snapshot(iid_b, adv_shares=5_000_000, spread_bps=10.0)
    body_b = client.get("/api/instrument/BBB/liquidity").json
    assert body_b["rank_in_watchlist"] == 1
    assert body_b["watchlist_size"] == 2
