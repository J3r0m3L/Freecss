"""Shared helpers for pulling and aligning daily returns from `bar_daily`
(DESIGN.md §9). bucket_pca, regression, and residual all need the same trick:
fetch the most-recent N rows per instrument, then align by date so cosine /
covariance / OLS get a clean matrix.
"""
from __future__ import annotations

from server.db import rows


def daily_close_series(instrument_id: int, *, lookback: int) -> list[tuple[str, float]]:
    """Return [(date_iso, close), ...] ordered ASC for the trailing `lookback` rows."""
    data = rows(
        "SELECT date, c FROM bar_daily WHERE instrument_id=? "
        "ORDER BY date DESC LIMIT ?",
        (instrument_id, lookback),
    )
    data.reverse()  # back to ascending
    return [(r["date"], r["c"]) for r in data if r["c"] is not None and r["c"] > 0]


def returns_from_closes(closes: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Pct returns from ASC-sorted (date, close) pairs."""
    out: list[tuple[str, float]] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1][1]
        cur = closes[i][1]
        if prev <= 0:
            continue
        out.append((closes[i][0], (cur - prev) / prev))
    return out


def aligned_returns(
    instrument_ids: list[int], *, lookback: int,
) -> tuple[list[str], dict[int, list[float]]]:
    """Date-aligned daily returns matrix.

    Returns (dates, returns_by_id) where `returns_by_id[iid][k]` is the return
    on `dates[k]`. Dates are the intersection of all series so the returned
    rows form a dense matrix suitable for PCA / OLS.
    """
    per_id: dict[int, dict[str, float]] = {}
    for iid in instrument_ids:
        series = returns_from_closes(daily_close_series(iid, lookback=lookback + 1))
        per_id[iid] = dict(series)

    if not per_id:
        return [], {}

    # Intersection of dates across all series.
    common = set.intersection(*(set(d.keys()) for d in per_id.values()))
    dates = sorted(common)
    matrix = {iid: [per_id[iid][d] for d in dates] for iid in instrument_ids}
    return dates, matrix
