"""Scheduler jobs (DESIGN.md §7.3). Every job records a `job_run` row — the
single source of truth for the UI's "last updated" badges and /api/health."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone

from server.db import get_db

log = logging.getLogger("deleveraging_watch.jobs")


@contextmanager
def record_run(job_name: str):
    """Write a job_run row: 'running' on entry, 'ok'/'error' on exit.

    Yields a small mutable dict; set `result['rows']` to record rows_written.
    """
    started = datetime.now(timezone.utc).isoformat()
    db = get_db()
    db.execute(
        "INSERT INTO job_run(job_name, started_at, status) VALUES(?,?,'running')",
        (job_name, started),
    )
    db.commit()
    result: dict = {"rows": None}
    try:
        yield result
    except Exception as exc:  # noqa: BLE001
        log.exception("job %s failed", job_name)
        db.execute(
            "UPDATE job_run SET finished_at=?, status='error', error_message=? "
            "WHERE job_name=? AND started_at=?",
            (datetime.now(timezone.utc).isoformat(), str(exc), job_name, started),
        )
        db.commit()
        raise
    else:
        db.execute(
            "UPDATE job_run SET finished_at=?, status='ok', rows_written=? "
            "WHERE job_name=? AND started_at=?",
            (datetime.now(timezone.utc).isoformat(), result.get("rows"), job_name, started),
        )
        db.commit()
