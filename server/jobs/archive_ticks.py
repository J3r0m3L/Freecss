"""archive_ticks (§7.3, §6 Notes). Nightly.

Move every `tick` row older than 30 days into a per-year Parquet file under
`<repo_root>/data/archive/`, then VACUUM to reclaim space. The tick table
otherwise grows ~80MB/symbol/day; capping the hot window keeps SQLite responsive.

Parquet is the right archive format: small, columnar, future-readable by any
analytics tool. If `pyarrow` isn't importable we fall back to CSV.gz — the data
isn't lost, just less compact.
"""
from __future__ import annotations

import csv
import gzip
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from server.config import config
from server.db import execute, rows
from server.jobs import record_run

log = logging.getLogger("deleveraging_watch.jobs.archive_ticks")

HOT_WINDOW_DAYS = 30
_ARCHIVE_DIR = config.repo_root / "data" / "archive"


def _by_year(records: list[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for r in records:
        try:
            year = int(r["ts"][:4])
        except Exception:  # noqa: BLE001
            continue
        out.setdefault(year, []).append(r)
    return out


def _write_parquet(year: int, records: list[dict]) -> Path | None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except Exception:  # noqa: BLE001
        return None
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = _ARCHIVE_DIR / f"ticks_{year}.parquet"
    table = pa.table({k: [r.get(k) for r in records]
                       for k in ("instrument_id", "ts", "bid", "ask", "last",
                                 "bid_size", "ask_size", "trade_size")})
    # Append-friendly: write to a per-batch file then merge if the year-file exists.
    if path.exists():
        existing = pq.read_table(path)
        table = pa.concat_tables([existing, table])
    pq.write_table(table, path)
    return path


def _write_csv_gz(year: int, records: list[dict]) -> Path:
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = _ARCHIVE_DIR / f"ticks_{year}.csv.gz"
    new_file = not path.exists()
    mode = "wt" if new_file else "at"
    fields = ("instrument_id", "ts", "bid", "ask", "last",
              "bid_size", "ask_size", "trade_size")
    with gzip.open(path, mode) as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new_file:
            w.writeheader()
        for r in records:
            w.writerow({k: r.get(k) for k in fields})
    return path


def run(*, hot_window_days: int = HOT_WINDOW_DAYS) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=hot_window_days)).isoformat()
    with record_run("archive_ticks") as result:
        cold = rows(
            "SELECT instrument_id, ts, bid, ask, last, bid_size, ask_size, "
            "trade_size FROM tick WHERE ts < ? ORDER BY ts", (cutoff,),
        )
        if not cold:
            result["rows"] = 0
            return

        for year, records in _by_year(cold).items():
            written = _write_parquet(year, records)
            fmt = "parquet"
            if written is None:
                written = _write_csv_gz(year, records)
                fmt = "csv.gz"
            log.info("archive_ticks: wrote %d rows for %d as %s (%s)",
                     len(records), year, fmt, written)

        execute("DELETE FROM tick WHERE ts < ?", (cutoff,))
        # SQLite VACUUM rebuilds the file in-place; ~constant-time relative to
        # the active row count, not the deleted set.
        execute("VACUUM")
        result["rows"] = len(cold)
