"""/api/notes CRUD + from-news / from-social + related_notes."""
from server.db import one


def test_empty(client):
    assert client.get("/api/notes").json == []


def test_create_global_note_embeds_body(client):
    resp = client.post("/api/notes", json={"body": "Watching macro tariff risk."})
    assert resp.status_code == 201
    nid = resp.json["id"]
    row = one("SELECT body_embedding FROM update_log WHERE id=?", (nid,))
    # Global notes are FinBERT-embedded on insert (§7.1).
    assert row["body_embedding"] is not None


def test_create_per_symbol_note_skips_embedding(client, make_watch):
    iid, _ = make_watch("AAPL")
    resp = client.post("/api/notes",
                       json={"body": "Watch AAPL", "instrument_id": iid})
    nid = resp.json["id"]
    row = one("SELECT instrument_id, body_embedding FROM update_log WHERE id=?", (nid,))
    assert row["instrument_id"] == iid and row["body_embedding"] is None


def test_create_rejects_both_linked_news_and_social(client):
    resp = client.post("/api/notes", json={
        "body": "x", "linked_news_id": 1, "linked_social_post_id": 2,
    })
    assert resp.status_code == 400


def test_from_news_attaches_to_first_watched_ticker(
    client, make_watch_with_profile, seed_news,
):
    iid_aapl, _ = make_watch_with_profile("AAPL", "BULL")
    nid = seed_news(tickers=["AAPL"])
    resp = client.post(f"/api/notes/from-news/{nid}")
    assert resp.status_code == 201
    assert resp.json["instrument_id"] == iid_aapl
    assert resp.json["linked_news_id"] == nid


def test_from_news_falls_back_to_global_if_no_watch_matches(
    client, seed_news,
):
    nid = seed_news(tickers=["ZZZZ"])  # nobody watches ZZZZ
    resp = client.post(f"/api/notes/from-news/{nid}")
    assert resp.status_code == 201
    assert resp.json["instrument_id"] is None


def test_from_news_unknown_404(client):
    assert client.post("/api/notes/from-news/99999").status_code == 404


def test_from_social_attaches_to_first_watched_ticker(
    client, make_watch_with_profile, seed_social_post,
):
    iid, _ = make_watch_with_profile("AAPL", "BULL")
    pid = seed_social_post(tickers=["AAPL"])
    resp = client.post(f"/api/notes/from-social/{pid}")
    assert resp.status_code == 201
    assert resp.json["instrument_id"] == iid
    assert resp.json["linked_social_post_id"] == pid


def test_scope_filter(client, make_watch):
    iid, _ = make_watch("AAPL")
    client.post("/api/notes", json={"body": "global"})
    client.post("/api/notes", json={"body": "per-sym", "instrument_id": iid})
    g = client.get("/api/notes?scope=global").json
    s = client.get(f"/api/notes?scope=symbol&instrument_id={iid}").json
    assert [n["body"] for n in g] == ["global"]
    assert [n["body"] for n in s] == ["per-sym"]


def test_scope_symbol_without_instrument_400(client):
    assert client.get("/api/notes?scope=symbol").status_code == 400


def test_related_notes_returns_globals_above_cutoff(
    client, make_watch_with_profile,
):
    # The cosine path requires an embedded global note AND a profile_embedding.
    iid, _ = make_watch_with_profile("AAPL", "BULL")
    # Both bodies pass through the same stub FinBERT, so cosine is well-defined.
    client.post("/api/notes", json={"body": "Tech company exposed to rates and tariffs."})
    client.post("/api/notes", json={"body": "Completely different unrelated text."})
    body = client.get("/api/instrument/AAPL/related_notes?cosine_min=0.0").json
    # Threshold 0.0 returns both notes ordered by cosine desc.
    assert len(body) == 2
    assert body[0]["cosine"] >= body[1]["cosine"]


def test_related_notes_unknown_404(client):
    assert client.get("/api/instrument/ZZZZ/related_notes").status_code == 404
