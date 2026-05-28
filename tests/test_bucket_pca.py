"""bucket_pca (DESIGN.md §3.4, §9)."""
from server.analytics.bucket_pca import MIN_OBS, fit_bucket


def test_no_candidates_returns_empty():
    r = fit_bucket(bucket_id=1, candidates=[])
    assert r.representative_id is None
    assert r.pc1_var_explained == 0.0
    assert r.note == "no candidates"


def test_single_candidate_auto_wins(make_watch):
    iid, _ = make_watch("LONE")
    r = fit_bucket(bucket_id=1, candidates=[(iid, "LONE")])
    assert r.representative_id == iid
    assert r.pc1_var_explained == 1.0
    assert r.note == "single candidate"


def test_picks_member_with_largest_pc1_loading(seed_correlated_daily_bars, make_watch):
    """A 3-ETF basket where SPY-like names load near-identically on PC1.
    PCA picks one — exact identity is alphabetical tiebreak when loadings tie."""
    a, _ = make_watch("AAA")
    b, _ = make_watch("BBB")
    c, _ = make_watch("CCC")
    # All three load on the same market with tiny idiosyncratic noise.
    seed_correlated_daily_bars(
        [(a, 1.0, 0.0005), (b, 1.0, 0.0005), (c, 1.0, 0.0005)],
        n=100, seed=7,
    )
    r = fit_bucket(bucket_id=1, candidates=[(a, "AAA"), (b, "BBB"), (c, "CCC")])
    assert r.representative_id in (a, b, c)
    # Highly cohesive basket → PC1 should explain most of the variance.
    assert r.pc1_var_explained > 0.85
    # Loadings should all be roughly equal magnitude.
    vals = list(r.loadings.values())
    assert min(vals) > 0.4 and max(vals) < 0.75


def test_insufficient_observations_falls_back(seed_daily_bars, make_watch):
    iid, _ = make_watch("SHORT")
    iid2, _ = make_watch("SHORT2")
    # Fewer rows than MIN_OBS → falls back to first candidate with note set.
    seed_daily_bars(iid,  [100 + i * 0.1 for i in range(MIN_OBS - 5)])
    seed_daily_bars(iid2, [100 + i * 0.2 for i in range(MIN_OBS - 5)])
    r = fit_bucket(bucket_id=1,
                   candidates=[(iid, "SHORT"), (iid2, "SHORT2")])
    assert r.representative_id == iid
    assert r.pc1_var_explained == 0.0
    assert "insufficient observations" in r.note


def test_no_aligned_returns_returns_empty(make_watch):
    iid_a, _ = make_watch("EMPTY_A")
    iid_b, _ = make_watch("EMPTY_B")
    # No bar_daily rows for either → aligned_returns is empty.
    r = fit_bucket(bucket_id=1,
                   candidates=[(iid_a, "EMPTY_A"), (iid_b, "EMPTY_B")])
    assert r.representative_id is None
    assert r.note == "no aligned returns"
