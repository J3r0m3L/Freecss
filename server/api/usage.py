"""GET /api/usage (DESIGN.md §7.1, §11) — SUM over api_cost_event.

Always shows actual billable spend recorded at call time; a vendor price change
mid-month doesn't invalidate history because `unit_cost_usd` is persisted per
row. Default window: month-to-date in UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from server.db import rows

bp = Blueprint("usage", __name__, url_prefix="/api")


def _month_start_utc() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


@bp.get("/usage")
def usage():
    since = request.args.get("since") or _month_start_utc()
    until = request.args.get("until") or datetime.now(timezone.utc).isoformat()
    group_by = (request.args.get("group_by") or "source").lower()

    by_source = rows(
        "SELECT source, SUM(units) units, SUM(cost_usd) cost_usd "
        "FROM api_cost_event WHERE ts >= ? AND ts <= ? GROUP BY source ORDER BY source",
        (since, until),
    )
    total = sum(float(r["cost_usd"] or 0) for r in by_source)

    body = {
        "since": since,
        "until": until,
        "total_usd": round(total, 4),
        "by_source": [{
            "source": r["source"],
            "units": int(r["units"] or 0),
            "cost_usd": round(float(r["cost_usd"] or 0), 4),
        } for r in by_source],
    }

    if group_by in ("day", "month"):
        # SQLite date(...) gives YYYY-MM-DD; substr(...,1,7) gives YYYY-MM.
        bucket_expr = "substr(ts,1,10)" if group_by == "day" else "substr(ts,1,7)"
        series = rows(
            f"SELECT {bucket_expr} bucket, source, "
            "SUM(units) units, SUM(cost_usd) cost_usd "
            "FROM api_cost_event WHERE ts >= ? AND ts <= ? "
            "GROUP BY bucket, source ORDER BY bucket, source",
            (since, until),
        )
        body["series"] = [{
            "bucket": r["bucket"],
            "source": r["source"],
            "units": int(r["units"] or 0),
            "cost_usd": round(float(r["cost_usd"] or 0), 4),
        } for r in series]

    return jsonify(body)
