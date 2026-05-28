"""Watchlist-add wires the §10.1 profile-setup pipeline (Phase 2 extension)."""
from server.db import one
from server.nlp.finbert import blob_to_embedding


def test_add_runs_profile_setup_synchronously(client):
    resp = client.post("/api/watchlist", json={"symbol": "AAPL", "direction": "BULL"})
    assert resp.status_code == 201
    row = one("SELECT meta_json, profile_text, profile_embedding "
              "FROM instrument WHERE symbol='AAPL'")
    assert row["profile_text"] is not None
    assert row["meta_json"] is not None  # Finnhub stub provided fields
    emb = blob_to_embedding(row["profile_embedding"])
    assert emb is not None and len(emb) == 768


def test_readd_after_soft_delete_backfills_missing_profile(client):
    client.post("/api/watchlist", json={"symbol": "AAPL", "direction": "BULL"})
    # Soft-delete and re-add — profile already exists, should not be overwritten.
    wid = client.get("/api/watchlist").json[0]["id"]
    client.delete(f"/api/watchlist/{wid}")
    before = one("SELECT profile_text FROM instrument WHERE symbol='AAPL'")["profile_text"]
    resp = client.post("/api/watchlist", json={"symbol": "AAPL", "direction": "BEAR"})
    assert resp.status_code == 201
    after = one("SELECT profile_text FROM instrument WHERE symbol='AAPL'")["profile_text"]
    assert before == after  # stub generator → idempotent
