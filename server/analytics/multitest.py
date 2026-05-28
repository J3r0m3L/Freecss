"""Benjamini–Hochberg false-discovery-rate adjustment (DESIGN.md §9).

With 80 buckets a naive p<0.05 would expose ~4 false-positive bucket exposures
per watch on average. BH @ q=0.05 keeps the expected false-positive proportion
in the surfaced set ≤ 5% while being strictly less conservative than Bonferroni.

This is the single canonical implementation — every call site (factor_refresh
and any future test-suite checks) goes through it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BHResult:
    q_values: list[float]      # adjusted, parallel to input order
    significant: list[bool]    # True where q ≤ alpha
    k_significant: int         # count of True


def bh_fdr(pvalues: list[float], *, alpha: float = 0.05) -> BHResult:
    """Two-stage BH-FDR.

    Step 1: sort p ascending, find the largest k with `p_(k) ≤ (k / m) · alpha`;
    everything ranked ≤ k is significant.
    Step 2: produce monotone-adjusted q-values via the standard pratio
    cumulative-min trick, then re-permute into the input order.

    Inputs containing NaN/None are treated as q=1.0 (never significant) and do
    not consume an FDR rank — matches `statsmodels.stats.multipletests` behavior.
    """
    m = len(pvalues)
    if m == 0:
        return BHResult(q_values=[], significant=[], k_significant=0)

    valid = [(i, p) for i, p in enumerate(pvalues)
             if p is not None and not _is_nan(p)]
    n = len(valid)
    if n == 0:
        return BHResult(q_values=[1.0] * m, significant=[False] * m,
                        k_significant=0)

    valid.sort(key=lambda t: t[1])
    # Raw "qhat" then enforce monotone non-increasing from the largest k down,
    # which is the standard BH cumulative-min step.
    qhat = [min(1.0, p * n / (rank + 1)) for rank, (_, p) in enumerate(valid)]
    for j in range(n - 2, -1, -1):
        qhat[j] = min(qhat[j], qhat[j + 1])

    q_values = [1.0] * m
    significant = [False] * m
    for (orig_idx, _), q in zip(valid, qhat):
        q_values[orig_idx] = q
        significant[orig_idx] = q <= alpha

    return BHResult(q_values=q_values, significant=significant,
                    k_significant=sum(significant))


def _is_nan(x: float) -> bool:
    return x != x  # NaN is the only IEEE float not equal to itself
