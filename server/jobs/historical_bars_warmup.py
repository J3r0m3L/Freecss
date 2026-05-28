"""historical_bars_warmup (DESIGN.md §9 follow-up, Phase 3 bulk-loader).

Runs on startup. For every instrument that's either an active watch OR a
candidate in some `factor_bucket`, pull the trailing ~6 months of daily bars
from Massive REST and write them into `bar_daily`.

Without this the Context tab is empty for ~6 months until enough daily bars
accumulate from live observation. We skip any instrument that already has
enough recent rows so reruns are cheap (and the job is safe to run repeatedly).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from server.adapters.massive_daily import fetch_daily_bars
from server.db import execute, one, rows
from server.jobs import record_run

log = logging.getLogger("deleveraging_watch.jobs.historical_bars_warmup")

DEFAULT_LOOKBACK_DAYS = 180   # ~6 calendar months
ENOUGH_ROWS_THRESHOLD = 100   # skip if we already have this many recent rows


def _targets() -> list[tuple[int, str]]:
    """Active watches ∪ all factor_bucket candidates. Dedup by instrument_id."""
    seen: dict[int, str] = {}
    for r in rows(
        "SELECT DISTINCT i.id, i.symbol FROM watch w "
        "JOIN instrument i ON i.id=w.instrument_id WHERE w.active=1"
    ):
        seen[r["id"]] = r["symbol"]
    for r in rows(
        "SELECT DISTINCT i.id, i.symbol FROM factor_bucket_candidate c "
        "JOIN instrument i ON i.id=c.instrument_id "
        "JOIN factor_bucket b ON b.id=c.bucket_id WHERE b.active=1"
    ):
        seen.setdefault(r["id"], r["symbol"])
    return sorted(seen.items(), key=lambda t: t[1])


def _already_warm(instrument_id: int, *, since: str) -> bool:
    row = one(
        "SELECT COUNT(*) c FROM bar_daily WHERE instrument_id=? AND date >= ?",
        (instrument_id, since),
    )
    return (row or {"c": 0})["c"] >= ENOUGH_ROWS_THRESHOLD


def _persist(instrument_id: int, bars: list) -> int:
    """REPLACE INTO so reruns refresh prices but don't duplicate rows."""
    wrote = 0
    for b in bars:
        try:
            execute(
                "INSERT OR REPLACE INTO bar_daily(instrument_id, date, o, h, l, c, v, vwap) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (instrument_id, b.date.isoformat(), b.o, b.h, b.l, b.c, b.v, b.vwap),
            )
            wrote += 1
        except Exception:  # noqa: BLE001
            log.exception("bar_daily insert failed for instrument_id=%s date=%s",
                          instrument_id, b.date)
    return wrote


def run(*, lookback_days: int = DEFAULT_LOOKBACK_DAYS, force: bool = False) -> None:
    with record_run("historical_bars_warmup") as result:
        since_iso = (date.today() - timedelta(days=lookback_days)).isoformat()
        wrote_total = 0
        skipped = 0
        for iid, symbol in _targets():
            if not force and _already_warm(iid, since=since_iso):
                skipped += 1
                continue
            try:
                bars = fetch_daily_bars(symbol, days=lookback_days)
            except Exception:  # noqa: BLE001
                log.exception("daily-bars fetch failed for %s", symbol)
                continue
            wrote_total += _persist(iid, bars)
        log.info("historical_bars_warmup: wrote=%s, skipped_already_warm=%s",
                 wrote_total, skipped)
        result["rows"] = wrote_total
