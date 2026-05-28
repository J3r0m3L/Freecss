"""profile_text_refresh (§7.3, §10.1). Monthly on the 1st Sunday at 03:30 local.
Skips any symbol whose profile_text was regenerated in the last 7 days.

Currently a thin wrapper around setup_profile per instrument — that function
pulls fresh Finnhub meta, asks Haiku for a new exposure paragraph, and re-
embeds. Failures per symbol are logged and don't halt the batch.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from server.db import rows
from server.jobs import record_run
from server.nlp.profile_setup import setup_profile

log = logging.getLogger("deleveraging_watch.jobs.profile_text_refresh")

_SKIP_IF_REFRESHED_WITHIN_DAYS = 7


def run() -> None:
    with record_run("profile_text_refresh") as result:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=_SKIP_IF_REFRESHED_WITHIN_DAYS)
                  ).isoformat()
        targets = rows(
            "SELECT i.id, i.symbol FROM instrument i JOIN watch w ON w.instrument_id=i.id "
            "WHERE w.active=1 AND (i.meta_refreshed_at IS NULL OR i.meta_refreshed_at < ?) "
            "ORDER BY i.symbol",
            (cutoff,),
        )
        done = 0
        for r in targets:
            try:
                setup_profile(r["id"])
                done += 1
            except Exception:  # noqa: BLE001
                log.exception("profile_text_refresh failed for %s", r["symbol"])
        result["rows"] = done
