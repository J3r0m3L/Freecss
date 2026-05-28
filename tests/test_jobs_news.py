"""End-to-end of the Phase 2 jobs: news poll, X poll, earnings sync, profile
refresh — all running entirely off stub adapters."""
from datetime import datetime, timezone

from server.db import execute, one, rows
from server.jobs import earnings_sync, massive_news_poll, profile_text_refresh, x_account_poll


def test_massive_news_poll_persists_dedupes_and_broadcasts(
    make_watch_with_profile, fake_socketio,
):
    iid, _ = make_watch_with_profile("AAPL", "BULL")
    massive_news_poll.run(socketio=fake_socketio)

    persisted = rows("SELECT * FROM news ORDER BY id")
    # Stub returns 2 deterministic items for AAPL (one beats, one probe) — both
    # land via the symbol-match path so both clear the 0.5 floor.
    assert len(persisted) == 2
    assert all("AAPL" in r["tickers_json"] for r in persisted)

    events = [e for e, _ in fake_socketio.emissions if e == "news"]
    assert len(events) == 2

    # Both stub headlines pass the persist floor:
    #   - 'beats' (positive) is aligned with a BULL thesis → info-tier, adverse=0
    #   - 'probe' (negative) is adverse to BULL with critical-ladder rel/sent
    # Both still get an alert row; only the probe is adverse.
    alerts = rows("SELECT kind, severity, adverse FROM alert WHERE kind='news' ORDER BY id")
    assert len(alerts) == 2
    assert sorted(a["adverse"] for a in alerts) == [0, 1]
    adverse_row = next(a for a in alerts if a["adverse"] == 1)
    assert adverse_row["severity"] == "critical"

    # Second invocation in the same minute: massive_id dedupe drops everything.
    fake_socketio.emissions.clear()
    massive_news_poll.run(socketio=fake_socketio)
    assert rows("SELECT id FROM news") == persisted_ids(persisted)
    assert all(e != "news" for e, _ in fake_socketio.emissions)


def persisted_ids(rows_):
    return [{"id": r["id"]} for r in rows_]


def test_massive_news_records_zero_cost_event(make_watch_with_profile, fake_socketio):
    make_watch_with_profile("AAPL", "BULL")
    massive_news_poll.run(socketio=fake_socketio)
    cost = rows("SELECT * FROM api_cost_event WHERE source='massive:news'")
    assert len(cost) == 1
    assert cost[0]["cost_usd"] == 0.0
    assert cost[0]["units"] == 1  # one ticker polled


def test_x_account_poll_persists_and_alerts(make_watch_with_profile, fake_socketio):
    # Watch SPY — the X stub tweet mentions $SPY, so the ticker-match path fires.
    iid, _ = make_watch_with_profile("SPY", "BULL")
    # Ensure at least one curated account is in the table (seed loads them).
    assert one("SELECT 1 FROM social_account_watch WHERE active=1 LIMIT 1")
    x_account_poll.run(socketio=fake_socketio)

    posts = rows("SELECT * FROM social_post")
    # Stub fires one tweet per active account on first poll; $SPY cashtag in the
    # body lifts every one of them above the 0.5 relevance floor.
    assert len(posts) >= 1
    assert all(p["relevance"] >= 0.5 for p in posts)
    assert all("SPY" in p["tickers_json"] for p in posts)

    # last_post_id and last_polled_at should now be set on the polled accounts.
    polled = rows("SELECT last_post_id, last_polled_at FROM social_account_watch WHERE active=1")
    assert all(r["last_polled_at"] for r in polled)
    assert any(r["last_post_id"] for r in polled)


def test_earnings_sync_writes_one_event_per_active_watch(
    make_watch_with_profile, monkeypatch,
):
    iid_a, _ = make_watch_with_profile("AAPL", "BULL")
    iid_m, _ = make_watch_with_profile("MSFT", "BULL")
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    earnings_sync.run()
    out = rows("SELECT instrument_id, when_hint FROM earnings ORDER BY instrument_id")
    assert {r["instrument_id"] for r in out} == {iid_a, iid_m}
    assert all(r["when_hint"] == "bmo" for r in out)


def test_profile_text_refresh_processes_only_stale(make_watch):
    """A symbol refreshed within the skip window is excluded; an old one runs."""
    iid_fresh, _ = make_watch("FRESH")
    iid_stale, _ = make_watch("STALE")
    # Fresh: refreshed just now → should be skipped.
    execute(
        "UPDATE instrument SET meta_refreshed_at=? WHERE id=?",
        (datetime.now(timezone.utc).isoformat(), iid_fresh),
    )
    # Stale: never refreshed (meta_refreshed_at IS NULL) → should run.
    profile_text_refresh.run()
    rj = one("SELECT rows_written FROM job_run WHERE job_name='profile_text_refresh' "
             "ORDER BY started_at DESC LIMIT 1")
    assert rj["rows_written"] == 1

    fresh = one("SELECT profile_text FROM instrument WHERE id=?", (iid_fresh,))
    stale = one("SELECT profile_text FROM instrument WHERE id=?", (iid_stale,))
    assert fresh["profile_text"] is None
    assert stale["profile_text"] is not None
