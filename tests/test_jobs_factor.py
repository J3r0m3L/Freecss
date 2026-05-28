"""End-to-end Phase 3 jobs against the stub daily-bars adapter."""
from server.db import execute, one, rows
from server.jobs import factor_pca, factor_refresh, historical_bars_warmup, residual_intraday


def test_historical_bars_warmup_fills_bar_daily(monkeypatch, make_watch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    # Active watch on AAPL forces it into the targets list (plus all 80
    # buckets' candidates) — keep this lookback small for test speed.
    make_watch("AAPL")
    historical_bars_warmup.run(lookback_days=40)
    n = one("SELECT COUNT(*) c FROM bar_daily")["c"]
    assert n > 100  # warmup pulled many ETFs at 40 rows each


def test_historical_bars_warmup_skips_already_warm(monkeypatch, make_watch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    make_watch("AAPL")
    historical_bars_warmup.run(lookback_days=40)
    first = one("SELECT COUNT(*) c FROM bar_daily")["c"]
    # Second pass with same lookback should skip everything that's already warm.
    historical_bars_warmup.run(lookback_days=40)
    second = one("SELECT COUNT(*) c FROM bar_daily")["c"]
    assert second == first


def test_factor_pca_chooses_representatives(monkeypatch, make_watch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    make_watch("AAPL")
    historical_bars_warmup.run(lookback_days=140)
    factor_pca.run(lookback_days=120)

    chosen = rows(
        "SELECT label, representative_id, pc1_var_explained "
        "FROM factor_bucket WHERE representative_id IS NOT NULL"
    )
    # At least the well-known multi-ETF buckets should get a rep.
    labels = {r["label"] for r in chosen}
    assert "S&P 500" in labels
    assert "7-10Y rates (belly)" in labels
    # Loadings written back too.
    loaded = one("SELECT COUNT(*) c FROM factor_bucket_candidate "
                 "WHERE pc1_loading IS NOT NULL")
    assert loaded["c"] > 50


def test_factor_refresh_writes_significant_exposures(monkeypatch, make_watch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    iid_aapl, wid = make_watch("AAPL")
    historical_bars_warmup.run(lookback_days=140)
    factor_pca.run(lookback_days=120)
    factor_refresh.run(window_days=90)

    exps = rows("SELECT bucket_id, beta, p_value, q_value, significant "
                "FROM factor_exposure WHERE watch_id=?", (wid,))
    assert len(exps) > 30, "expected exposures across most buckets"
    # Some should pass BH-FDR (AAPL stub loads on 'broad' factor with β≈1).
    assert any(e["significant"] for e in exps)
    # q-values are always defined and ≤ 1.
    assert all(0 <= e["q_value"] <= 1 for e in exps)


def test_factor_refresh_noop_without_buckets(make_watch):
    make_watch("AAPL")
    # No PCA run yet → no buckets have representative_id → factor_refresh
    # writes zero rows and records 'ok'.
    factor_refresh.run()
    rec = one("SELECT rows_written, status FROM job_run "
              "WHERE job_name='factor_refresh' ORDER BY started_at DESC LIMIT 1")
    assert rec["status"] == "ok" and (rec["rows_written"] or 0) == 0


def test_residual_intraday_updates_only_last_residual(monkeypatch, make_watch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    iid_aapl, wid = make_watch("AAPL")
    historical_bars_warmup.run(lookback_days=140)
    factor_pca.run(lookback_days=120)
    factor_refresh.run(window_days=90)
    # Seed a fake intraday move on AAPL + one rep ETF so the residual computes.
    rep = one("SELECT representative_id FROM factor_bucket "
              "WHERE representative_id IS NOT NULL LIMIT 1")
    iid_rep = rep["representative_id"]
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    execute("INSERT INTO bar_1m(instrument_id, ts, o, h, l, c, v) "
            "VALUES(?,?,?,?,?,?,?)", (iid_aapl, now, 100, 100, 100, 102, 1000))
    execute("INSERT INTO bar_1m(instrument_id, ts, o, h, l, c, v) "
            "VALUES(?,?,?,?,?,?,?)", (iid_rep, now, 200, 200, 200, 201, 1000))
    residual_intraday.run()
    populated = one(
        "SELECT COUNT(*) c FROM factor_exposure "
        "WHERE watch_id=? AND last_residual IS NOT NULL", (wid,),
    )
    assert populated["c"] >= 1
