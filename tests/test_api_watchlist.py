"""Watchlist CRUD round-trips (DESIGN.md §7.1)."""


def _add(client, symbol: str, direction: str = "BULL", **extra):
    return client.post("/api/watchlist",
                       json={"symbol": symbol, "direction": direction, **extra})


def test_empty_watchlist(client):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    assert r.json == []


def test_add_then_list(client):
    r = _add(client, "AAPL", "BULL")
    assert r.status_code == 201
    body = r.json
    assert body["symbol"] == "AAPL"
    assert body["direction"] == "BULL"
    assert body["active"] is True

    listing = client.get("/api/watchlist").json
    assert [w["symbol"] for w in listing] == ["AAPL"]


def test_duplicate_returns_409(client):
    _add(client, "AAPL")
    r = _add(client, "AAPL")
    assert r.status_code == 409
    assert "already" in r.json["error"]


def test_invalid_direction_returns_400(client):
    r = _add(client, "FOO", direction="SIDEWAYS")
    assert r.status_code == 400
    assert "BULL" in r.json["error"]


def test_missing_symbol_returns_400(client):
    r = client.post("/api/watchlist", json={"direction": "BULL"})
    assert r.status_code == 400


def test_patch_updates_direction_and_thresholds(client):
    wid = _add(client, "MSFT", "BULL").json["id"]
    r = client.patch(f"/api/watchlist/{wid}",
                     json={"direction": "BEAR",
                           "thresholds": {"px_jump_pct": 0.05, "position_size": 100}})
    assert r.status_code == 200
    listing = {w["symbol"]: w for w in client.get("/api/watchlist").json}
    assert listing["MSFT"]["direction"] == "BEAR"
    assert listing["MSFT"]["thresholds"]["px_jump_pct"] == 0.05
    assert listing["MSFT"]["thresholds"]["position_size"] == 100


def test_delete_is_soft_and_reactivatable(client):
    wid = _add(client, "NVDA").json["id"]
    assert client.delete(f"/api/watchlist/{wid}").status_code == 200
    assert client.get("/api/watchlist").json == []
    # Soft-deleted row is reactivated with a fresh thesis on re-add.
    r = _add(client, "NVDA", "BEAR")
    assert r.status_code == 201
    assert r.json["direction"] == "BEAR"


def test_delete_nonexistent_404(client):
    assert client.delete("/api/watchlist/9999").status_code == 404


def test_patch_no_fields_400(client):
    wid = _add(client, "TSLA").json["id"]
    assert client.patch(f"/api/watchlist/{wid}", json={}).status_code == 400
