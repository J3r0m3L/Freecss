"""/api/buckets — candidate-basket editor (Phase 5)."""
from server.db import execute, one, rows


def test_list_buckets_returns_seeded_universe(client):
    body = client.get("/api/buckets").json
    # Seed loads 80 buckets.
    assert len(body) == 80
    assert all("label" in b for b in body)
    assert all("representative_symbol" in b for b in body)


def test_get_bucket_returns_candidates(client):
    bid = one("SELECT id FROM factor_bucket WHERE label='S&P 500'")["id"]
    body = client.get(f"/api/buckets/{bid}").json
    assert body["label"] == "S&P 500"
    symbols = {c["symbol"] for c in body["candidates"]}
    # Seeded basket per DESIGN.md §9.
    assert symbols == {"SPY", "IVV", "VOO"}


def test_get_bucket_unknown_404(client):
    assert client.get("/api/buckets/99999").status_code == 404


def test_add_candidate_creates_new_instrument(client):
    bid = one("SELECT id FROM factor_bucket WHERE label='S&P 500'")["id"]
    resp = client.post(f"/api/buckets/{bid}/candidates", json={"symbol": "VTI"})
    assert resp.status_code == 201
    # Instrument was created on-the-fly and the candidate row is now present.
    inst = one("SELECT id FROM instrument WHERE symbol='VTI'")
    assert inst is not None
    assert one("SELECT 1 FROM factor_bucket_candidate WHERE bucket_id=? "
               "AND instrument_id=?", (bid, inst["id"])) is not None


def test_add_candidate_duplicate_409(client):
    bid = one("SELECT id FROM factor_bucket WHERE label='Nasdaq-100'")["id"]
    # QQQ is already a seeded candidate of Nasdaq-100.
    assert client.post(f"/api/buckets/{bid}/candidates",
                       json={"symbol": "QQQ"}).status_code == 409


def test_add_candidate_missing_symbol_400(client):
    bid = one("SELECT id FROM factor_bucket WHERE label='S&P 500'")["id"]
    assert client.post(f"/api/buckets/{bid}/candidates",
                       json={}).status_code == 400


def test_add_candidate_unknown_bucket_404(client):
    assert client.post("/api/buckets/99999/candidates",
                       json={"symbol": "FOO"}).status_code == 404


def test_remove_candidate_succeeds_for_non_rep(client):
    bid = one("SELECT id FROM factor_bucket WHERE label='S&P 500'")["id"]
    # No PCA has run yet → representative_id is NULL → any removal allowed.
    assert client.delete(f"/api/buckets/{bid}/candidates/VOO").status_code == 200
    # Idempotency / re-removal → 404 (already gone).
    assert client.delete(f"/api/buckets/{bid}/candidates/VOO").status_code == 404


def test_remove_rep_blocked_409(client):
    """Removing the current rep is gated — the user must refit PCA first."""
    bid = one("SELECT id FROM factor_bucket WHERE label='S&P 500'")["id"]
    spy_iid = one("SELECT id FROM instrument WHERE symbol='SPY'")["id"]
    execute("UPDATE factor_bucket SET representative_id=? WHERE id=?", (spy_iid, bid))
    resp = client.delete(f"/api/buckets/{bid}/candidates/SPY")
    assert resp.status_code == 409
    assert "representative" in resp.json["error"]


def test_remove_unknown_symbol_404(client):
    bid = one("SELECT id FROM factor_bucket WHERE label='S&P 500'")["id"]
    assert client.delete(f"/api/buckets/{bid}/candidates/ZZZZ").status_code == 404


def test_refit_pca_sets_representative(client, monkeypatch):
    bid = one("SELECT id FROM factor_bucket WHERE label='S&P 500'")["id"]
    # Stub the daily-bars fetch so the warm DB shortcut isn't required.
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)

    # Warm the candidate bars first via the historical-bars job (mirrors the
    # real startup sequence).
    from server.jobs.historical_bars_warmup import run as warmup_run
    warmup_run(lookback_days=140)

    resp = client.post(f"/api/buckets/{bid}/refit_pca")
    assert resp.status_code == 200
    body = resp.json
    assert body["ok"] is True
    assert body["representative_symbol"] in {"SPY", "IVV", "VOO"}
    assert body["pc1_var_explained"] is not None


def test_refit_pca_unknown_bucket_404(client):
    assert client.post("/api/buckets/99999/refit_pca").status_code == 404
