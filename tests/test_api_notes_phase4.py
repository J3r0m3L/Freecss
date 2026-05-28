"""Phase 4 additions to /api/notes: from-alert, DELETE, denormalized symbol."""
from datetime import datetime, timezone

from server.db import execute


def _seed_alert(iid: int) -> int:
    cur = execute(
        "INSERT INTO alert(instrument_id, ts, kind, severity, adverse, payload_json) "
        "VALUES(?,?,?,?,?,?)",
        (iid, datetime.now(timezone.utc).isoformat(), "px_jump", "high", 1,
         '{"pct": -0.05}'),
    )
    return cur.lastrowid


def test_from_alert_creates_linked_note(client, make_watch):
    iid, _ = make_watch("AAPL")
    aid = _seed_alert(iid)
    resp = client.post(f"/api/notes/from-alert/{aid}")
    assert resp.status_code == 201
    body = resp.json
    assert body["linked_alert_id"] == aid
    assert body["instrument_id"] == iid
    assert "AAPL" in body["body"]
    assert "px_jump" in body["body"]


def test_from_alert_unknown_404(client):
    assert client.post("/api/notes/from-alert/99999").status_code == 404


def test_delete_note(client):
    resp = client.post("/api/notes", json={"body": "ephemeral"})
    nid = resp.json["id"]
    assert client.delete(f"/api/notes/{nid}").status_code == 200
    assert client.get("/api/notes").json == []


def test_delete_unknown_404(client):
    assert client.delete("/api/notes/99999").status_code == 404


def test_list_includes_symbol_for_per_symbol_notes(client, make_watch):
    iid, _ = make_watch("AAPL")
    client.post("/api/notes", json={"body": "tied to AAPL", "instrument_id": iid})
    client.post("/api/notes", json={"body": "global"})
    body = client.get("/api/notes").json
    by_body = {n["body"]: n for n in body}
    assert by_body["tied to AAPL"]["symbol"] == "AAPL"
    assert by_body["global"]["symbol"] is None
