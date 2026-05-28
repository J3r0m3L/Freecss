"""OLS per (watch, bucket-representative) — DESIGN.md §9.

For each watch × bucket-rep, fit `r_symbol_t = α + β · r_rep_t + ε_t` on a
rolling window of daily returns. We persist β, α, R², ρ, p-value, and the
sample size; the caller (factor_refresh job) then runs BH-FDR across the 80
buckets for the watch and writes `significant = 1` for the survivors.

scipy is preferred for the p-value (uses the proper t-distribution); we fall
back to a normal approximation if scipy isn't importable for some reason.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np

from server.analytics.bars import aligned_returns

log = logging.getLogger("deleveraging_watch.analytics.regression")

DEFAULT_WINDOW_DAYS = 90
MIN_OBS = 30   # below this the standard error blows up and p-values stop meaning anything


@dataclass(frozen=True)
class OLSResult:
    beta: float
    intercept: float
    r_squared: float
    correlation: float
    p_value: float
    n_obs: int
    note: str = ""

    @property
    def is_estimable(self) -> bool:
        return self.n_obs >= MIN_OBS and not math.isnan(self.beta)


def _p_value_for_beta(beta: float, se: float, n: int) -> float:
    if se <= 0 or n <= 2:
        return 1.0
    t = beta / se
    try:
        from scipy import stats
        # two-sided p under H0: β = 0
        return float(2 * (1 - stats.t.cdf(abs(t), df=n - 2)))
    except Exception:  # pragma: no cover — scipy ships with the analytics extras
        # Normal approximation: fine for n >> 30.
        return float(2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2)))))


def fit(y: list[float], x: list[float]) -> OLSResult:
    """Fit y = α + β·x. Inputs already date-aligned and same length."""
    n = min(len(y), len(x))
    if n < 2:
        return OLSResult(beta=float("nan"), intercept=float("nan"),
                         r_squared=0.0, correlation=0.0, p_value=1.0,
                         n_obs=n, note="too few observations")
    y = np.asarray(y[:n], dtype=float)
    x = np.asarray(x[:n], dtype=float)

    x_mean = x.mean()
    y_mean = y.mean()
    sxx = float(((x - x_mean) ** 2).sum())
    if sxx == 0:
        return OLSResult(beta=0.0, intercept=float(y_mean), r_squared=0.0,
                         correlation=0.0, p_value=1.0, n_obs=n,
                         note="x has zero variance")
    sxy = float(((x - x_mean) * (y - y_mean)).sum())
    beta = sxy / sxx
    alpha = float(y_mean - beta * x_mean)

    y_hat = alpha + beta * x
    residuals = y - y_hat
    ss_res = float((residuals ** 2).sum())
    ss_tot = float(((y - y_mean) ** 2).sum())
    r_squared = 0.0 if ss_tot == 0 else 1.0 - ss_res / ss_tot

    # Pearson ρ.
    sxx_sqrt = math.sqrt(sxx)
    syy_sqrt = math.sqrt(ss_tot) if ss_tot > 0 else 0.0
    correlation = 0.0 if (sxx_sqrt == 0 or syy_sqrt == 0) else sxy / (sxx_sqrt * syy_sqrt)

    # Std error of β under standard OLS assumptions.
    if n > 2:
        sigma2 = ss_res / (n - 2)
        se_beta = math.sqrt(sigma2 / sxx) if sigma2 > 0 else 0.0
    else:
        se_beta = 0.0
    p_value = _p_value_for_beta(beta, se_beta, n)

    return OLSResult(beta=beta, intercept=alpha, r_squared=r_squared,
                     correlation=correlation, p_value=p_value, n_obs=n)


def fit_pair(
    watch_instrument_id: int, rep_instrument_id: int, *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> OLSResult:
    """Pull aligned returns from bar_daily and fit OLS."""
    _dates, mat = aligned_returns(
        [watch_instrument_id, rep_instrument_id], lookback=window_days,
    )
    y = mat.get(watch_instrument_id, [])
    x = mat.get(rep_instrument_id, [])
    return fit(y, x)
