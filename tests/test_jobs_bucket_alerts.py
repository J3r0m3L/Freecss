"""End-to-end of the bucket_alerts job (Phase 5)."""
from datetime import datetime, timezone

from server.db import execute, one, rows
from server.jobs import bucket_alerts


def _seed_significant_exposure(*, watch_id: int, bucket_id: int, beta: float):
    execute(
        "INSERT OR REPLACE INTO factor_exposure(watch_id, bucket_id, window_days, "
        "beta, intercept, r_squared, p_value, q_value, significant, correlation, "
        "computed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (watch_id, bucket_id, 90, beta, 0.0, 0.5, 0.001, 0.01, 1, 0.7,
         datetime.now(timezone.utc).isoformat()),
    )


def _set_rep(bucket_id: int, rep_iid: int) -> None:
    execute("UPDATE factor_bucket SET representative_id=?, active=1 WHERE id=?",
            (rep_iid, bucket_id))


def test_disabled_setting_is_noop(make_watch, fake_socketio):
    iid, wid = make_watch("AAPL")
    bucket = one("SELECT id FROM factor_bucket ORDER BY id LIMIT 1")
    rep_iid, _ = make_watch("REP")
    _set_rep(bucket["id"], rep_iid)
    _seed_significant_exposure(watch_id=wid, bucket_id=bucket["id"], beta=1.0)

    from server.db import set_setting
    set_setting("global", {"bucket_alerts": {"enabled": False}})

    bucket_alerts.run(socketio=fake_socketio)
    rec = one("SELECT status, rows_written FROM job_run "
              "WHERE job_name='bucket_alerts' ORDER BY started_at DESC LIMIT 1")
    assert rec["status"] == "ok" and (rec["rows_written"] or 0) == 0
    assert rows("SELECT * FROM alert") == []


def test_default_setting_is_enabled(make_watch, fake_socketio, monkeypatch):
    """No `setting('global').bucket_alerts` row → default ON (Phase 5 choice)."""
    iid, wid = make_watch("AAPL")
    bucket = one("SELECT id FROM factor_bucket ORDER BY id LIMIT 1")
    rep_iid, _ = make_watch("REP")
    _set_rep(bucket["id"], rep_iid)
    _seed_significant_exposure(watch_id=wid, bucket_id=bucket["id"], beta=1.0)

    # Stub out the z-score so the job sees a tradable signal without seeding bars.
    import server.jobs.bucket_alerts as ba
    from server.analytics.bucket_zscore import BucketZ
    monkeypatch.setattr(ba, "bucket_zscore",
                        lambda iid: BucketZ(z=-4.5, today_return=-0.04,
                                             baseline_mean=0.0,
                                             baseline_std=0.01, n_samples=60))

    bucket_alerts.run(socketio=fake_socketio)
    alerts = rows("SELECT kind, severity, adverse, payload_json FROM alert")
    assert len(alerts) == 1
    assert alerts[0]["kind"].startswith("factor:")
    assert alerts[0]["severity"] == "high"
    assert alerts[0]["adverse"] == 1


def test_one_z_computation_per_rep_across_many_watches(
    make_watch, fake_socketio, monkeypatch,
):
    """If three watches share a bucket-rep, we should compute z once, not 3x."""
    iid_a, wid_a = make_watch("AAA")
    iid_b, wid_b = make_watch("BBB")
    iid_c, wid_c = make_watch("CCC")
    bucket = one("SELECT id FROM factor_bucket ORDER BY id LIMIT 1")
    rep_iid, _ = make_watch("REP")
    _set_rep(bucket["id"], rep_iid)
    for wid in (wid_a, wid_b, wid_c):
        _seed_significant_exposure(watch_id=wid, bucket_id=bucket["id"], beta=1.0)

    import server.jobs.bucket_alerts as ba
    from server.analytics.bucket_zscore import BucketZ

    calls = {"count": 0}

    def _counting_z(iid: int):
        calls["count"] += 1
        return BucketZ(z=-3.5, today_return=-0.03,
                       baseline_mean=0.0, baseline_std=0.01, n_samples=60)

    monkeypatch.setattr(ba, "bucket_zscore", _counting_z)

    bucket_alerts.run(socketio=fake_socketio)
    assert calls["count"] == 1


def test_no_significant_exposures_is_noop(make_watch, fake_socketio):
    make_watch("AAPL")
    bucket_alerts.run(socketio=fake_socketio)
    rec = one("SELECT rows_written FROM job_run "
              "WHERE job_name='bucket_alerts' ORDER BY started_at DESC LIMIT 1")
    assert (rec["rows_written"] or 0) == 0


def test_dedup_namespaces_by_bucket(make_watch, fake_socketio, monkeypatch):
    """Two buckets fire on the same watch within 15 min: both alerts persist
    because the kind includes the bucket label."""
    iid, wid = make_watch("AAPL")
    bids = [r["id"] for r in rows("SELECT id FROM factor_bucket ORDER BY id LIMIT 2")]
    for i, bid in enumerate(bids):
        rep_iid, _ = make_watch(f"REP{i}")
        _set_rep(bid, rep_iid)
        _seed_significant_exposure(watch_id=wid, bucket_id=bid, beta=1.0)

    import server.jobs.bucket_alerts as ba
    from server.analytics.bucket_zscore import BucketZ
    monkeypatch.setattr(ba, "bucket_zscore",
                        lambda iid: BucketZ(z=-3.5, today_return=-0.03,
                                             baseline_mean=0.0,
                                             baseline_std=0.01, n_samples=60))

    bucket_alerts.run(socketio=fake_socketio)
    alerts = rows("SELECT kind FROM alert ORDER BY kind")
    # One alert per bucket — dedup did NOT collapse them because kinds differ.
    assert len(alerts) == 2
    assert len({a["kind"] for a in alerts}) == 2
