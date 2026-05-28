"""Schema init + seed loading (DESIGN.md §6, §9, §10.3)."""
from server.db import init_db, one, rows


def test_seeds_load_full_universe():
    assert one("SELECT COUNT(*) c FROM factor_bucket")["c"] == 80
    # Sanity: each bucket has at least one candidate.
    orphans = one(
        "SELECT COUNT(*) c FROM factor_bucket fb "
        "WHERE NOT EXISTS (SELECT 1 FROM factor_bucket_candidate c WHERE c.bucket_id=fb.id)"
    )
    assert orphans["c"] == 0
    # 205 candidates was the count after seeding (matches the catalog in §9).
    assert one("SELECT COUNT(*) c FROM factor_bucket_candidate")["c"] == 205
    assert one("SELECT COUNT(*) c FROM social_account_watch")["c"] == 15


def test_init_db_is_idempotent():
    before = one("SELECT COUNT(*) c FROM factor_bucket")["c"]
    init_db()  # called again by the fixture; explicit second call should be a no-op.
    init_db()
    after = one("SELECT COUNT(*) c FROM factor_bucket")["c"]
    assert before == after


def test_factor_buckets_have_known_labels():
    labels = {r["label"] for r in rows("SELECT label FROM factor_bucket")}
    # Spot-check across the §9 categories.
    for must_have in ("S&P 500", "VIX", "AI", "Semis", "Gold", "Bitcoin"):
        assert must_have in labels, f"missing bucket: {must_have!r}"


def test_x_accounts_are_x_only_in_v1():
    sources = {r["source"] for r in rows("SELECT DISTINCT source FROM social_account_watch")}
    assert sources == {"x"}, sources
