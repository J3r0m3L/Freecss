"""PCA over a bucket's candidate basket → pick the representative ETF.

DESIGN.md §3.4, §9: for each `factor_bucket`, the ETF whose return loads
*most strongly* on PC1 (the first principal component of the basket's return
matrix) is the canonical proxy — by construction it's the single ETF that best
spans what the whole basket has in common.

The function returns a PCAResult per bucket; the caller (factor_pca job)
persists `factor_bucket.representative_id`, `pc1_var_explained`, and writes
loadings back to `factor_bucket_candidate.pc1_loading`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from server.analytics.bars import aligned_returns

log = logging.getLogger("deleveraging_watch.analytics.bucket_pca")

DEFAULT_LOOKBACK_DAYS = 126   # ~6 trading-months per DESIGN.md §9
MIN_OBS = 30                  # below this PCA estimates are noise


@dataclass(frozen=True)
class PCAResult:
    bucket_id: int
    representative_id: int | None     # None if insufficient data
    representative_symbol: str | None
    pc1_var_explained: float          # 0..1
    loadings: dict[int, float]        # {instrument_id: |loading on PC1|}
    n_obs: int                        # rows in the aligned matrix
    note: str = ""


def fit_bucket(
    bucket_id: int, candidates: list[tuple[int, str]], *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> PCAResult:
    """Run PCA over the candidate basket; pick the rep ETF.

    `candidates`: [(instrument_id, symbol), ...]. Caller filters out inactive /
    missing rows beforehand.
    """
    if not candidates:
        return PCAResult(bucket_id=bucket_id, representative_id=None,
                         representative_symbol=None, pc1_var_explained=0.0,
                         loadings={}, n_obs=0, note="no candidates")

    iids = [iid for iid, _ in candidates]
    sym_by_id = {iid: sym for iid, sym in candidates}

    # Short-circuit before any data fetch: a singleton basket is its own rep,
    # even if bar_daily is empty (warmup hasn't reached it yet).
    if len(candidates) == 1:
        only_iid = candidates[0][0]
        return PCAResult(
            bucket_id=bucket_id, representative_id=only_iid,
            representative_symbol=sym_by_id[only_iid],
            pc1_var_explained=1.0, loadings={only_iid: 1.0},
            n_obs=0, note="single candidate",
        )

    dates, matrix = aligned_returns(iids, lookback=lookback_days)

    # Drop any candidate that has no returns at all (e.g. brand-new ETF).
    present = [iid for iid in iids if matrix.get(iid)]
    if not present:
        return PCAResult(bucket_id=bucket_id, representative_id=None,
                         representative_symbol=None, pc1_var_explained=0.0,
                         loadings={}, n_obs=0, note="no aligned returns")

    if len(present) == 1:
        iid = present[0]
        return PCAResult(
            bucket_id=bucket_id, representative_id=iid,
            representative_symbol=sym_by_id[iid],
            pc1_var_explained=1.0, loadings={iid: 1.0},
            n_obs=len(matrix[iid]), note="single candidate",
        )

    # n_obs × n_candidates matrix, centered per-column. Variance-normalize so a
    # high-vol member doesn't dominate PC1 purely on scale.
    X = np.column_stack([matrix[iid] for iid in present]).astype(float)
    if X.shape[0] < MIN_OBS:
        return PCAResult(bucket_id=bucket_id, representative_id=present[0],
                         representative_symbol=sym_by_id[present[0]],
                         pc1_var_explained=0.0, loadings={present[0]: 1.0},
                         n_obs=X.shape[0],
                         note=f"insufficient observations ({X.shape[0]} < {MIN_OBS})")

    X -= X.mean(axis=0, keepdims=True)
    std = X.std(axis=0, keepdims=True)
    std[std == 0] = 1.0  # guard against constant columns
    Xn = X / std

    # SVD is the numerically stable PCA path.
    try:
        _u, s, vt = np.linalg.svd(Xn, full_matrices=False)
    except np.linalg.LinAlgError as exc:
        log.warning("PCA SVD failed for bucket_id=%s: %s", bucket_id, exc)
        return PCAResult(bucket_id=bucket_id, representative_id=present[0],
                         representative_symbol=sym_by_id[present[0]],
                         pc1_var_explained=0.0, loadings={present[0]: 1.0},
                         n_obs=X.shape[0], note=f"SVD failed: {exc}")

    pc1 = vt[0]                              # length n_candidates
    total_var = float((s ** 2).sum()) or 1.0
    pc1_var_explained = float(s[0] ** 2) / total_var

    abs_loadings = np.abs(pc1)
    loadings_by_id = {iid: float(l) for iid, l in zip(present, abs_loadings)}

    # Tie-break alphabetical for deterministic test output.
    winner_idx = int(np.argmax(abs_loadings))
    winner_iid = present[winner_idx]
    ties = [iid for iid, l in loadings_by_id.items()
            if abs(l - abs_loadings[winner_idx]) < 1e-12]
    if len(ties) > 1:
        winner_iid = sorted(ties, key=lambda i: sym_by_id[i])[0]

    return PCAResult(
        bucket_id=bucket_id, representative_id=winner_iid,
        representative_symbol=sym_by_id[winner_iid],
        pc1_var_explained=pc1_var_explained, loadings=loadings_by_id,
        n_obs=X.shape[0],
    )
