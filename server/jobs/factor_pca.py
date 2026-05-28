"""factor_pca (DESIGN.md §7.3, §3.4, §9).

Runs on startup (if any bucket is missing a representative or its last PCA was
≥90 days ago) AND quarterly. For each active bucket:
1. Pull the candidate-basket instrument ids/symbols.
2. Fit PCA over the trailing ~6mo of daily returns.
3. Persist representative_id + pc1_var_explained + selected_at on factor_bucket;
   write per-candidate |PC1 loading| back to factor_bucket_candidate.

This job is a prerequisite for `factor_refresh`. Without representatives, the
OLS layer can't fire.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from server.analytics.bucket_pca import DEFAULT_LOOKBACK_DAYS, fit_bucket
from server.db import execute, rows
from server.jobs import record_run

log = logging.getLogger("deleveraging_watch.jobs.factor_pca")


def _bucket_candidates(bucket_id: int) -> list[tuple[int, str]]:
    return [(r["instrument_id"], r["symbol"]) for r in rows(
        "SELECT c.instrument_id, i.symbol FROM factor_bucket_candidate c "
        "JOIN instrument i ON i.id=c.instrument_id WHERE c.bucket_id=? "
        "ORDER BY i.symbol",
        (bucket_id,),
    )]


def run(*, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> None:
    with record_run("factor_pca") as result:
        buckets = rows("SELECT id, label FROM factor_bucket WHERE active=1 ORDER BY id")
        now_iso = datetime.now(timezone.utc).isoformat()
        chosen = 0

        for bucket in buckets:
            bucket_id = bucket["id"]
            candidates = _bucket_candidates(bucket_id)
            res = fit_bucket(bucket_id, candidates, lookback_days=lookback_days)

            if res.representative_id is None:
                log.info("bucket=%s skipped (%s)", bucket["label"], res.note)
                continue

            execute(
                "UPDATE factor_bucket SET representative_id=?, pc1_var_explained=?, "
                "selected_at=? WHERE id=?",
                (res.representative_id, res.pc1_var_explained, now_iso, bucket_id),
            )
            for iid, loading in res.loadings.items():
                execute(
                    "UPDATE factor_bucket_candidate SET pc1_loading=?, last_pca_at=? "
                    "WHERE bucket_id=? AND instrument_id=?",
                    (loading, now_iso, bucket_id, iid),
                )
            chosen += 1

        result["rows"] = chosen
        log.info("factor_pca: chose representatives for %d/%d buckets",
                 chosen, len(buckets))
