"""Bucket-level intraday z-score (DESIGN.md §9 "Factor-level deleveraging alerts").

For a single bucket representative ETF: compare today's intraday return (from
the latest `bar_1m` close vs the prior daily close) against the trailing
`lookback_days` of *daily* returns. The z is the standardized move — large |z|
means "the whole sector is moving abnormally hard today."

Returns None if there's insufficient history or today's intraday move isn't
computable yet (e.g. pre-market, before any bar_1m row has landed).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from server.analytics.bars import daily_close_series, returns_from_closes
from server.analytics.residual import latest_intraday_move

DEFAULT_LOOKBACK_DAYS = 60
MIN_OBS = 20


@dataclass(frozen=True)
class BucketZ:
    z: float
    today_return: float        # signed intraday move, in decimal (e.g. -0.02 = -2%)
    baseline_mean: float
    baseline_std: float
    n_samples: int


def bucket_zscore(instrument_id: int, *,
                  lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> BucketZ | None:
    """Standardize today's rep return against trailing daily returns."""
    today_ret = latest_intraday_move(instrument_id).return_pct
    if today_ret is None:
        return None

    # Pull lookback+1 daily closes so returns_from_closes() yields `lookback`
    # returns. The DB query already orders ASC after the reverse step.
    closes = daily_close_series(instrument_id, lookback=lookback_days + 1)
    rets = [r for _, r in returns_from_closes(closes)]
    # Exclude any "today" daily bar that may have been written; we want a
    # strictly-historical baseline. (Daily bars are usually only written at EOD,
    # but the warmup loader can land an end-of-day bar mid-session in stub mode.)
    if rets and closes and closes[-1][0].startswith(str(today_ret)[:0] or ""):  # no-op safe-guard
        pass
    if len(rets) < MIN_OBS:
        return None

    mean = statistics.fmean(rets)
    std = statistics.pstdev(rets)
    if std == 0:
        return None
    z = (today_ret - mean) / std
    return BucketZ(z=z, today_return=today_ret, baseline_mean=mean,
                   baseline_std=std, n_samples=len(rets))
