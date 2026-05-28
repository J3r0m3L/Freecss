"""residual_intraday (DESIGN.md §7.3, §9). Every 60s during session.

For every persisted (watch, bucket) row in `factor_exposure`, recompute today's
`last_residual` from the latest live representative-ETF + watched-symbol prices
in `bar_1m`. Only updates one column — the regression coefficients themselves
are refreshed EOD by `factor_refresh`.

Cheap: O(active_watches × significant_buckets) DB updates per minute; under v1
loads that's well under 1k writes.
"""
from __future__ import annotations

import logging

from server.analytics.residual import latest_intraday_move
from server.db import execute, rows
from server.jobs import record_run

log = logging.getLogger("deleveraging_watch.jobs.residual_intraday")


def run() -> None:
    with record_run("residual_intraday") as result:
        # Pull every estimable exposure row + the joined rep instrument_id.
        exposures = rows(
            "SELECT fe.watch_id, fe.bucket_id, fe.beta, fe.intercept, "
            "       w.instrument_id AS watch_iid, b.representative_id "
            "FROM factor_exposure fe "
            "JOIN watch w  ON w.id = fe.watch_id "
            "JOIN factor_bucket b ON b.id = fe.bucket_id "
            "WHERE w.active=1 AND b.active=1 AND b.representative_id IS NOT NULL"
        )
        if not exposures:
            result["rows"] = 0
            return

        # Cache intraday returns per instrument so we hit the DB once each.
        cache: dict[int, float | None] = {}

        def _ret(iid: int) -> float | None:
            if iid not in cache:
                cache[iid] = latest_intraday_move(iid).return_pct
            return cache[iid]

        updated = 0
        for e in exposures:
            r_rep = _ret(e["representative_id"])
            r_watch = _ret(e["watch_iid"])
            if r_rep is None or r_watch is None:
                continue
            expected = e["intercept"] + e["beta"] * r_rep
            residual = r_watch - expected
            execute(
                "UPDATE factor_exposure SET last_residual=? WHERE watch_id=? AND bucket_id=?",
                (residual, e["watch_id"], e["bucket_id"]),
            )
            updated += 1
        result["rows"] = updated
        log.debug("residual_intraday: updated %d rows", updated)
