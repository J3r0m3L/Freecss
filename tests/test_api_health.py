"""/api/health shape (DESIGN.md §14)."""
from datetime import datetime, timezone


def test_health_shape(client):
    body = client.get("/api/health").json
    assert set(body.keys()) >= {"feed", "notifier", "jobs"}
    assert set(body["feed"].keys()) >= {"adapter", "status", "last_tick_age_s", "symbols_live"}
    # No live feed in tests → no_data.
    assert body["feed"]["status"] == "no_data"
    assert body["jobs"] == []


def test_health_reports_latest_job_run(client):
    from server.db import execute

    started = datetime.now(timezone.utc).isoformat()
    execute("INSERT INTO job_run(job_name, started_at, status) VALUES(?,?,'ok')",
            ("threshold_evaluator", started))
    body = client.get("/api/health").json
    names = [j["job_name"] for j in body["jobs"]]
    assert "threshold_evaluator" in names
