"""liquidity_refresh job (Phase 4)."""
from datetime import date, datetime, timedelta, timezone

from server.db import execute, one, rows
from server.jobs import liquidity_refresh


def _seed_daily(iid: int, n: int = 25, *, volume: int = 1_000_000):
    today = date.today()
    for i in range(n):
        d = (today - timedelta(days=(n - i))).isoformat()
        execute("INSERT OR REPLACE INTO bar_daily(instrument_id, date, o, h, l, c, v) "
                "VALUES(?,?,?,?,?,?,?)", (iid, d, 100, 100, 100, 100, volume))


def test_refresh_writes_one_snapshot_per_active_watch(make_watch):
    iid_a, _ = make_watch("AAPL")
    iid_b, _ = make_watch("MSFT")
    _seed_daily(iid_a)
    _seed_daily(iid_b)
    liquidity_refresh.run()
    snaps = rows("SELECT instrument_id FROM liquidity_daily")
    assert {s["instrument_id"] for s in snaps} >= {iid_a, iid_b}


def test_refresh_includes_bucket_reps_even_without_watch(make_watch):
    """Bucket reps need snapshots for the §11.C grid liquidity-rank to include them."""
    iid, _ = make_watch("AAPL")
    _seed_daily(iid)
    # Point the first seeded factor_bucket at AAPL just to give it a rep.
    bucket = one("SELECT id FROM factor_bucket ORDER BY id LIMIT 1")
    execute("UPDATE factor_bucket SET representative_id=? WHERE id=?",
            (iid, bucket["id"]))
    liquidity_refresh.run()
    # AAPL counted once even though it appears via both paths.
    snaps = rows("SELECT instrument_id FROM liquidity_daily WHERE instrument_id=?",
                 (iid,))
    assert len(snaps) == 1


def test_refresh_skips_empty_snapshots(make_watch):
    make_watch("NOPRICE")
    # No bar_daily / bar_1m rows for NOPRICE → snapshot is empty → not written.
    liquidity_refresh.run()
    assert rows("SELECT * FROM liquidity_daily") == []


def test_refresh_idempotent_overwrites_same_day(make_watch):
    iid, _ = make_watch("AAPL")
    _seed_daily(iid, volume=1_000_000)
    liquidity_refresh.run()
    first = one("SELECT computed_at FROM liquidity_daily WHERE instrument_id=?",
                (iid,))
    # Re-run after seeding higher volume; same-date row gets replaced.
    execute("UPDATE bar_daily SET v=2_000_000 WHERE instrument_id=?", (iid,))
    liquidity_refresh.run()
    after = one("SELECT adv_shares_21d, computed_at FROM liquidity_daily "
                "WHERE instrument_id=?", (iid,))
    assert after["adv_shares_21d"] == 2_000_000
    assert after["computed_at"] >= first["computed_at"]
