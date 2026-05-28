"""/api/social/accounts CRUD (DESIGN.md §7.1, §11.E)."""


def test_seed_loads_accounts(client):
    """The X-account seed (social_watch.yaml, 15 entries) is loaded on init."""
    body = client.get("/api/social/accounts").json
    handles = {a["handle"] for a in body}
    assert "realDonaldTrump" in handles
    assert "SecTreasury" in handles
    assert len(body) >= 15


def test_add_strips_leading_at_and_resolves_id(client, monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    resp = client.post("/api/social/accounts",
                       json={"handle": "@MyNewHandle", "label": "Test handle"})
    assert resp.status_code == 201
    body = resp.json
    assert body["handle"] == "MyNewHandle"
    assert body["label"] == "Test handle"
    assert body["external_id"] == "stub-MyNewHandle"  # from x_api stub


def test_add_duplicate_409(client):
    client.post("/api/social/accounts", json={"handle": "DupTest"})
    dup = client.post("/api/social/accounts", json={"handle": "DupTest"})
    assert dup.status_code == 409


def test_add_missing_handle_400(client):
    assert client.post("/api/social/accounts", json={}).status_code == 400


def test_patch_label_and_active(client):
    resp = client.post("/api/social/accounts", json={"handle": "Patchy"})
    aid = resp.json["id"]
    assert client.patch(f"/api/social/accounts/{aid}",
                        json={"label": "Renamed"}).status_code == 200
    assert client.patch(f"/api/social/accounts/{aid}",
                        json={"active": False}).status_code == 200
    body = client.get("/api/social/accounts?active=false").json
    [row] = [a for a in body if a["id"] == aid]
    assert row["label"] == "Renamed" and row["active"] is False


def test_patch_unknown_404(client):
    assert client.patch("/api/social/accounts/99999",
                        json={"label": "x"}).status_code == 404


def test_patch_no_fields_400(client):
    resp = client.post("/api/social/accounts", json={"handle": "NoFields"})
    aid = resp.json["id"]
    assert client.patch(f"/api/social/accounts/{aid}", json={}).status_code == 400


def test_delete_soft(client):
    resp = client.post("/api/social/accounts", json={"handle": "DelTest"})
    aid = resp.json["id"]
    assert client.delete(f"/api/social/accounts/{aid}").status_code == 200
    # No longer listed under active=true.
    handles = {a["handle"] for a in client.get("/api/social/accounts").json}
    assert "DelTest" not in handles
    # Still visible with active=false.
    handles_all = {a["handle"] for a in client.get("/api/social/accounts?active=false").json}
    assert "DelTest" in handles_all


def test_delete_unknown_404(client):
    assert client.delete("/api/social/accounts/99999").status_code == 404
