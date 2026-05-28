"""pushover_ack_poll (§7.3, §12) — every 30s, poll receipts for unacked
emergency-priority (priority=2) sends and record ack time. Idle (cheap early
exit) when there are no open emergencies."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

from server.db import get_db, rows
from server.jobs import record_run

log = logging.getLogger("deleveraging_watch.notify")


def run() -> None:
    open_emergencies = rows(
        "SELECT id, pushover_receipt FROM alert "
        "WHERE pushover_receipt IS NOT NULL AND acked_at IS NULL"
    )
    if not open_emergencies:
        return  # nothing to poll — don't even write a job_run row

    user_key = os.environ.get("PUSHOVER_USER_KEY", "")
    with record_run("pushover_ack_poll") as result:
        acked = 0
        db = get_db()
        for row in open_emergencies:
            receipt = row["pushover_receipt"]
            try:
                resp = requests.get(
                    f"https://api.pushover.net/1/receipts/{receipt}.json?token={user_key}",
                    timeout=10,
                )
                data = resp.json()
            except Exception:  # noqa: BLE001
                log.exception("ack poll failed for receipt %s", receipt)
                continue
            if data.get("acknowledged") == 1:
                db.execute(
                    "UPDATE alert SET acked_at=? WHERE id=?",
                    (datetime.now(timezone.utc).isoformat(), row["id"]),
                )
                acked += 1
        db.commit()
        result["rows"] = acked
