"""/api/alerts list + ack (DESIGN.md §7.1)."""
from datetime import datetime, timezone

from server.db import execute


def _seed_alert(iid: int, *, severity="warn", adverse=1, kind="px_jump") -> int:
    cur = execute(
        "INSERT INTO alert(instrument_id, ts, kind, severity, adverse, payload_json) "
        "VALUES(?,?,?,?,?,?)",
        (iid, datetime.now(timezone.utc).isoformat(), kind, severity, adverse,
         '{"pct": -0.05}'),
    )
    return cur.lastrowid


def test_empty(client):
    assert client.get("/api/alerts").json == []


def test_list_returns_recent_alerts(client, make_watch):
    iid, _ = make_watch("AAPL")
    _seed_alert(iid, severity="warn")
    _seed_alert(iid, severity="critical", kind="combined")
    body = client.get("/api/alerts").json
    assert len(body) == 2
    assert {a["severity"] for a in body} == {"warn", "critical"}
    assert all(a["symbol"] == "AAPL" for a in body)
    # payload is parsed JSON, not a string.
    assert isinstance(body[0]["payload"], dict)


def test_ack_marks_acked(client, make_watch):
    iid, _ = make_watch("AAPL")
    aid = _seed_alert(iid)
    assert client.post(f"/api/alerts/{aid}/ack").status_code == 200
    body = client.get("/api/alerts").json
    assert body[0]["acked_at"] is not None


def test_ack_unknown_404(client):
    assert client.post("/api/alerts/99999/ack").status_code == 404


def test_limit_param_caps(client, make_watch):
    iid, _ = make_watch("AAPL")
    for _ in range(5):
        _seed_alert(iid)
    body = client.get("/api/alerts?limit=2").json
    assert len(body) == 2
