"""factor_refresh (DESIGN.md §7.3, §9). EOD at 16:30 ET.

For each active watch × active bucket (with representative_id set):
  1. Pull aligned daily returns over the rolling window.
  2. Run OLS  y_watch = α + β·x_rep + ε.
  3. Collect p-values across all 80 buckets for this watch.
  4. Apply BH-FDR at q=0.05 → set `significant`.
  5. REPLACE INTO factor_exposure.

Without representatives (factor_pca hasn't run yet) this job does nothing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from server.analytics.multitest import bh_fdr
from server.analytics.regression import DEFAULT_WINDOW_DAYS, fit_pair
from server.db import execute, get_setting, rows
from server.jobs import record_run

log = logging.getLogger("deleveraging_watch.jobs.factor_refresh")


def _ready_buckets() -> list[dict]:
    return rows(
        "SELECT id AS bucket_id, label, representative_id "
        "FROM factor_bucket WHERE active=1 AND representative_id IS NOT NULL "
        "ORDER BY id"
    )


def _active_watches() -> list[dict]:
    return rows(
        "SELECT w.id AS watch_id, w.instrument_id, i.symbol "
        "FROM watch w JOIN instrument i ON i.id=w.instrument_id "
        "WHERE w.active=1 ORDER BY i.symbol"
    )


def _persist(*, watch_id: int, bucket_id: int, window_days: int, result,
             q_value: float, significant: bool) -> None:
    execute(
        "INSERT OR REPLACE INTO factor_exposure(watch_id, bucket_id, window_days, "
        "beta, intercept, r_squared, p_value, q_value, significant, correlation, "
        "computed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            watch_id, bucket_id, window_days,
            result.beta, result.intercept, result.r_squared,
            result.p_value, q_value, 1 if significant else 0,
            result.correlation, datetime.now(timezone.utc).isoformat(),
        ),
    )


def run(*, window_days: int | None = None) -> None:
    window_days = window_days or int(
        ((get_setting("global", {}) or {}).get("factor", {}) or {})
        .get("window_days", DEFAULT_WINDOW_DAYS)
    )

    with record_run("factor_refresh") as result:
        watches = _active_watches()
        buckets = _ready_buckets()
        if not watches or not buckets:
            log.info("factor_refresh: nothing to do (watches=%d buckets=%d)",
                     len(watches), len(buckets))
            result["rows"] = 0
            return

        written = 0
        for w in watches:
            fits: list = []
            pvalues: list[float] = []
            for b in buckets:
                fit = fit_pair(w["instrument_id"], b["representative_id"],
                               window_days=window_days)
                fits.append((b, fit))
                pvalues.append(fit.p_value if fit.is_estimable else float("nan"))

            bh = bh_fdr(pvalues, alpha=0.05)
            for (b, fit), q, sig in zip(fits, bh.q_values, bh.significant):
                if not fit.is_estimable:
                    continue
                _persist(watch_id=w["watch_id"], bucket_id=b["bucket_id"],
                         window_days=window_days, result=fit,
                         q_value=q, significant=bool(sig))
                written += 1
            log.info("factor_refresh: watch=%s wrote=%d significant=%d",
                     w["symbol"], len(fits), bh.k_significant)
        result["rows"] = written
