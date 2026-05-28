"""earnings_sync (§7.3) — daily 02:00. Pull the next 14 days of earnings for
each active watch from Finnhub; replace the table for those symbols so the
calendar always reflects the latest estimates."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from server.adapters.finnhub import fetch_earnings
from server.db import execute, rows
from server.jobs import record_run

log = logging.getLogger("deleveraging_watch.jobs.earnings_sync")

_LOOKAHEAD_DAYS = 14


def _active_symbols() -> list[tuple[int, str]]:
    return [(r["instrument_id"], r["symbol"]) for r in rows(
        "SELECT w.instrument_id, i.symbol FROM watch w JOIN instrument i "
        "ON i.id=w.instrument_id WHERE w.active=1"
    )]


def run() -> None:
    with record_run("earnings_sync") as result:
        active = _active_symbols()
        if not active:
            result["rows"] = 0
            return
        sym_to_id = {s: iid for iid, s in active}
        frm = date.today()
        to = frm + timedelta(days=_LOOKAHEAD_DAYS)
        events = fetch_earnings([s for _, s in active], frm=frm, to=to)
        now = datetime.now(timezone.utc).isoformat()

        # Replace future earnings for these symbols so dropped events disappear.
        execute(
            "DELETE FROM earnings WHERE instrument_id IN ("
            + ",".join(str(iid) for iid in sym_to_id.values())
            + ") AND scheduled_at >= ?",
            (datetime.combine(frm, datetime.min.time(), tzinfo=timezone.utc).isoformat(),),
        )
        wrote = 0
        for ev in events:
            iid = sym_to_id.get(ev.symbol.upper())
            if iid is None:
                continue
            try:
                execute(
                    "INSERT OR REPLACE INTO earnings(instrument_id, scheduled_at, "
                    "when_hint, eps_estimate, rev_estimate, fetched_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (iid, ev.scheduled_at.isoformat(), ev.when_hint,
                     ev.eps_estimate, ev.rev_estimate, now),
                )
                wrote += 1
            except Exception:  # noqa: BLE001
                log.exception("earnings insert failed for %s", ev.symbol)
        result["rows"] = wrote
