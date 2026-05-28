"""liquidity_refresh (§7.3, Phase 4). EOD 16:35 ET.

For each active watch instrument + every bucket-rep ETF, roll the trailing 21
daily bars and today's bar_1m / tick rows into a `liquidity_daily` snapshot.
The bucket reps are included so the §11.C grid liquidity-rank can include them.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from server.analytics.liquidity import compute_daily_snapshot
from server.db import execute, rows
from server.jobs import record_run

log = logging.getLogger("deleveraging_watch.jobs.liquidity_refresh")


def _targets() -> list[int]:
    seen: dict[int, None] = {}
    for r in rows("SELECT instrument_id FROM watch WHERE active=1"):
        seen[r["instrument_id"]] = None
    for r in rows(
        "SELECT representative_id AS instrument_id FROM factor_bucket "
        "WHERE active=1 AND representative_id IS NOT NULL"
    ):
        seen[r["instrument_id"]] = None
    return list(seen.keys())


def run(*, as_of: date | None = None) -> None:
    as_of = as_of or date.today()
    with record_run("liquidity_refresh") as result:
        wrote = 0
        for iid in _targets():
            snap = compute_daily_snapshot(iid, as_of=as_of)
            if snap.is_empty():
                continue
            execute(
                "INSERT OR REPLACE INTO liquidity_daily(instrument_id, date, "
                "adv_shares_21d, adv_dollar_21d, spread_avg_bps, pct_zero_volume, "
                "computed_at) VALUES(?,?,?,?,?,?,?)",
                (iid, as_of.isoformat(),
                 snap.adv_shares_21d, snap.adv_dollar_21d,
                 snap.spread_avg_bps, snap.pct_zero_volume,
                 datetime.now(timezone.utc).isoformat()),
            )
            wrote += 1
        result["rows"] = wrote
        log.info("liquidity_refresh wrote %d snapshots for %s", wrote, as_of)
