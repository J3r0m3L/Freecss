"""/api/health (DESIGN.md §7.1, §14): feed liveness, last-tick age, and the
latest job_run per scheduled job (powers the "last updated" badges in §11)."""
from __future__ import annotations

from flask import Blueprint, jsonify

from server import state
from server.config import config
from server.db import rows

bp = Blueprint("health", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    age = state.last_tick_age_s()
    # During an active feed, > 30s without a tick is "stalled" (§14).
    if age is None:
        feed_status = "no_data"
    elif age <= 30:
        feed_status = "live"
    else:
        feed_status = "stalled"

    jobs = rows(
        "SELECT j.job_name, j.started_at, j.finished_at, j.status, "
        "       j.rows_written, j.error_message "
        "FROM job_run j JOIN ("
        "  SELECT job_name, MAX(started_at) AS mx FROM job_run GROUP BY job_name"
        ") last ON last.job_name=j.job_name AND last.mx=j.started_at "
        "ORDER BY j.job_name"
    )
    snap = state.snapshot()
    return jsonify({
        "feed": {
            "adapter": config.data_adapter,
            "status": feed_status,
            "last_tick_age_s": age,
            "symbols_live": len(snap),
        },
        "notifier": config.notifier,
        "jobs": jobs,
    })
