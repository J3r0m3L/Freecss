"""BH-FDR (DESIGN.md §9)."""
import math

from server.analytics.multitest import bh_fdr


def test_empty_input():
    r = bh_fdr([])
    assert r.q_values == [] and r.significant == [] and r.k_significant == 0


def test_all_significant():
    """All tiny p-values → all should pass at q=0.05."""
    r = bh_fdr([0.0001] * 10, alpha=0.05)
    assert all(r.significant) and r.k_significant == 10
    assert all(q <= 0.05 for q in r.q_values)


def test_none_significant():
    """All p ≈ 1 → none should pass."""
    r = bh_fdr([0.9, 0.95, 0.99], alpha=0.05)
    assert not any(r.significant) and r.k_significant == 0


def test_partial_significance_preserves_input_order():
    pvalues = [0.5, 0.001, 0.04, 0.8, 0.02]
    r = bh_fdr(pvalues, alpha=0.05)
    # Sorted p = [0.001, 0.02, 0.04, 0.5, 0.8] at ranks 1..5.
    # BH thresholds = (k/5)·0.05 = [0.01, 0.02, 0.03, 0.04, 0.05].
    # Largest k with p_(k) ≤ threshold: k=2 (p=0.02, threshold=0.02). k=3 fails.
    # So the two original positions with p ∈ {0.001, 0.02} (orig indices 1 and 4)
    # are significant; the rest are not.
    assert r.significant == [False, True, False, False, True]


def test_nan_inputs_treated_as_non_significant():
    r = bh_fdr([0.001, float("nan"), 0.001], alpha=0.05)
    assert r.significant == [True, False, True]
    assert math.isclose(r.q_values[1], 1.0)


def test_q_values_are_monotone_under_sorted_p():
    p = sorted([0.001, 0.01, 0.04, 0.07, 0.2])
    r = bh_fdr(p, alpha=0.05)
    # Sorted q-values are non-decreasing (monotone in p).
    sorted_qs = sorted(r.q_values)
    assert sorted_qs == r.q_values  # input was already sorted ascending


def test_alpha_tunable():
    r_loose = bh_fdr([0.04, 0.04, 0.04], alpha=0.10)
    r_tight = bh_fdr([0.04, 0.04, 0.04], alpha=0.01)
    assert r_loose.k_significant > 0
    assert r_tight.k_significant == 0
