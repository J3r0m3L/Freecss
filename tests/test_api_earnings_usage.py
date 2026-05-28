"""/api/earnings + /api/usage."""
from datetime import datetime, timedelta, timezone

from server.db import execute


def test_empty_earnings(client):
    assert client.get("/api/earnings").json == []


def test_earnings_returns_watched_only(client, make_watch):
    iid_a, _ = make_watch("AAPL")
    iid_z, _ = make_watch("ZZZZ")
    when = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    execute(
        "INSERT INTO earnings(instrument_id, scheduled_at, when_hint, fetched_at) "
        "VALUES(?,?,?,?)",
        (iid_a, when, "bmo", datetime.now(timezone.utc).isoformat()),
    )
    body = client.get("/api/earnings").json
    assert [r["symbol"] for r in body] == ["AAPL"]
    assert body[0]["when_hint"] == "bmo"


def test_earnings_window_param(client, make_watch):
    iid, _ = make_watch("AAPL")
    soon = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    far = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    execute("INSERT INTO earnings(instrument_id, scheduled_at, when_hint, fetched_at) "
            "VALUES(?,?,?,?)", (iid, soon, "bmo", now))
    execute("INSERT INTO earnings(instrument_id, scheduled_at, when_hint, fetched_at) "
            "VALUES(?,?,?,?)", (iid, far, "amc", now))
    one_week = client.get("/api/earnings?window=7d").json
    assert len(one_week) == 1
    full_month = client.get("/api/earnings?window=60d").json
    assert len(full_month) == 2


def test_per_symbol_earnings_unknown_404(client):
    assert client.get("/api/instrument/ZZZZ/earnings").status_code == 404


def test_usage_default_window_is_mtd(client):
    body = client.get("/api/usage").json
    assert body["total_usd"] == 0
    assert body["by_source"] == []


def test_usage_sums_by_source(client):
    execute("INSERT INTO api_cost_event(source, units, unit_cost_usd, cost_usd) "
            "VALUES('x:tweets', 3, 0.005, 0.015)")
    execute("INSERT INTO api_cost_event(source, units, unit_cost_usd, cost_usd) "
            "VALUES('x:tweets', 2, 0.005, 0.010)")
    execute("INSERT INTO api_cost_event(source, units, unit_cost_usd, cost_usd) "
            "VALUES('x:user_read', 1, 0.010, 0.010)")
    body = client.get("/api/usage").json
    by_src = {r["source"]: r for r in body["by_source"]}
    assert by_src["x:tweets"]["units"] == 5
    assert abs(by_src["x:tweets"]["cost_usd"] - 0.025) < 1e-9
    assert abs(body["total_usd"] - 0.035) < 1e-9


def test_usage_group_by_day_includes_series(client):
    execute("INSERT INTO api_cost_event(source, units, unit_cost_usd, cost_usd) "
            "VALUES('x:tweets', 1, 0.005, 0.005)")
    body = client.get("/api/usage?group_by=day").json
    assert "series" in body and isinstance(body["series"], list)
