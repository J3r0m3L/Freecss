"""OLS regression (DESIGN.md §9)."""
import math

from server.analytics.regression import fit, fit_pair


def test_perfect_linear_fit_recovers_beta():
    x = [0.01, -0.02, 0.005, 0.0, -0.01, 0.03, -0.015]
    beta_true, alpha_true = 1.5, 0.0
    y = [alpha_true + beta_true * xi for xi in x]
    r = fit(y, x)
    assert abs(r.beta - beta_true) < 1e-9
    assert abs(r.intercept - alpha_true) < 1e-9
    assert abs(r.r_squared - 1.0) < 1e-9
    assert abs(r.correlation - 1.0) < 1e-9


def test_perfect_anti_correlation_negative_beta():
    x = [0.01, -0.02, 0.005, -0.01, 0.03]
    y = [-2.0 * xi for xi in x]
    r = fit(y, x)
    assert abs(r.beta - (-2.0)) < 1e-9
    assert abs(r.correlation - (-1.0)) < 1e-9


def test_zero_x_variance_returns_zero_beta():
    r = fit(y=[0.01, -0.02, 0.0], x=[0.005, 0.005, 0.005])
    assert r.beta == 0 and r.correlation == 0
    assert "zero variance" in r.note


def test_p_value_is_small_for_strong_relationship():
    # 50 obs of y = 1.0 * x with tiny noise: p should be essentially zero.
    import random
    rng = random.Random(0)
    x = [rng.gauss(0, 0.02) for _ in range(50)]
    y = [xi + rng.gauss(0, 0.0005) for xi in x]
    r = fit(y, x)
    assert r.p_value < 0.001


def test_p_value_large_for_pure_noise():
    import random
    rng = random.Random(1)
    x = [rng.gauss(0, 0.02) for _ in range(80)]
    y = [rng.gauss(0, 0.02) for _ in range(80)]
    r = fit(y, x)
    # Two independent gaussians: p-value should usually be > 0.1, but allow some slack.
    assert r.p_value > 0.05


def test_too_few_observations_flagged():
    r = fit(y=[0.01], x=[0.005])
    assert r.n_obs == 1
    assert not r.is_estimable


def test_fit_pair_uses_bar_daily(seed_correlated_daily_bars, make_watch):
    iid_y, _ = make_watch("STK")
    iid_x, _ = make_watch("REP")
    seed_correlated_daily_bars(
        [(iid_y, 1.2, 0.001), (iid_x, 1.0, 0.001)], n=120, seed=42,
    )
    r = fit_pair(iid_y, iid_x, window_days=100)
    # iid_y was generated as 1.2*market + noise, iid_x as 1.0*market + noise →
    # β should be roughly 1.2 / 1.0 = 1.2, ρ near 1.
    assert r.n_obs >= 30
    assert abs(r.beta - 1.2) < 0.05
    assert r.correlation > 0.95
    assert not math.isnan(r.p_value)
