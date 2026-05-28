"""/api/instrument/<sym>/exposures (DESIGN.md §7.1, §11.C)."""
from datetime import datetime, timezone

from server.db import execute


def _seed_exposure(*, watch_id: int, bucket_id: int, beta: float = 1.0,
                   p_value: float = 0.001, q_value: float = 0.01,
                   significant: int = 1, residual: float | None = None) -> None:
    execute(
        "INSERT OR REPLACE INTO factor_exposure(watch_id, bucket_id, window_days, "
        "beta, intercept, r_squared, p_value, q_value, significant, correlation, "
        "last_residual, computed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (watch_id, bucket_id, 90, beta, 0.0, 0.6, p_value, q_value,
         significant, 0.7, residual, datetime.now(timezone.utc).isoformat()),
    )


def _ensure_bucket_with_rep(symbol: str = "REP") -> tuple[int, int]:
    """Insert an instrument as the rep and point a seeded bucket at it."""
    cur = execute(
        "INSERT INTO instrument(symbol, display_name, asset_class, data_adapter) "
        "VALUES(?,?,?,?)", (symbol, symbol, "etf", "stub"),
    )
    rep_iid = cur.lastrowid
    # Use the first seeded bucket — guaranteed to exist via the factor_buckets seed.
    from server.db import one
    bucket = one("SELECT id FROM factor_bucket ORDER BY id LIMIT 1")
    execute("UPDATE factor_bucket SET representative_id=? WHERE id=?",
            (rep_iid, bucket["id"]))
    return bucket["id"], rep_iid


def test_unknown_symbol_404(client):
    assert client.get("/api/instrument/ZZZZ/exposures").status_code == 404


def test_no_watch_404(client):
    # Instrument exists but isn't on an active watch.
    execute("INSERT INTO instrument(symbol, display_name, asset_class, data_adapter) "
            "VALUES('ORPHAN','ORPHAN','equity','stub')")
    assert client.get("/api/instrument/ORPHAN/exposures").status_code == 404


def test_returns_significant_only_by_default(client, make_watch):
    iid, wid = make_watch("AAPL")
    bid, _ = _ensure_bucket_with_rep("REP")
    _seed_exposure(watch_id=wid, bucket_id=bid, beta=1.5, significant=1, q_value=0.001)

    # Add a non-significant one to confirm the default filter excludes it.
    from server.db import one
    bid2 = one("SELECT id FROM factor_bucket WHERE id != ? LIMIT 1", (bid,))["id"]
    # That bucket needs a representative too (the API joins it).
    execute("UPDATE factor_bucket SET representative_id=? WHERE id=?",
            (iid, bid2))   # any instrument id works for the join
    _seed_exposure(watch_id=wid, bucket_id=bid2, beta=0.3, significant=0, q_value=0.4)

    body = client.get("/api/instrument/AAPL/exposures").json
    assert body["significant_only"] is True
    assert len(body["exposures"]) == 1
    assert body["exposures"][0]["beta"] == 1.5


def test_significant_only_false_returns_all(client, make_watch):
    iid, wid = make_watch("AAPL")
    bid, _ = _ensure_bucket_with_rep("REP1")
    _seed_exposure(watch_id=wid, bucket_id=bid, beta=1.0, significant=0, q_value=0.4)
    body = client.get("/api/instrument/AAPL/exposures?significant_only=false").json
    assert len(body["exposures"]) == 1
    assert body["exposures"][0]["significant"] is False


def test_sorted_by_abs_beta_desc(client, make_watch):
    iid, wid = make_watch("AAPL")
    from server.db import rows
    # Get 3 distinct buckets and give each a rep.
    bids = [r["id"] for r in rows("SELECT id FROM factor_bucket ORDER BY id LIMIT 3")]
    for bid in bids:
        execute("UPDATE factor_bucket SET representative_id=? WHERE id=?",
                (iid, bid))
    _seed_exposure(watch_id=wid, bucket_id=bids[0], beta=0.5)
    _seed_exposure(watch_id=wid, bucket_id=bids[1], beta=-2.1)
    _seed_exposure(watch_id=wid, bucket_id=bids[2], beta=1.3)
    body = client.get("/api/instrument/AAPL/exposures").json
    betas = [e["beta"] for e in body["exposures"]]
    # |β|: 2.1 > 1.3 > 0.5
    assert betas == [-2.1, 1.3, 0.5]
