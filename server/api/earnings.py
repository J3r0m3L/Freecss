"""Earnings calendar (DESIGN.md §7.1, §11.C #6)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from server.db import one, rows

bp = Blueprint("earnings", __name__, url_prefix="/api")

_WINDOW_RE = re.compile(r"^(\d+)d$")


def _parse_window(s: str | None, default_days: int = 14) -> int:
    if not s:
        return default_days
    m = _WINDOW_RE.match(s.strip().lower())
    if not m:
        return default_days
    return max(1, min(int(m.group(1)), 365))


@bp.get("/earnings")
def list_upcoming():
    days = _parse_window(request.args.get("window"))
    now = datetime.now(timezone.utc).isoformat()
    until = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    data = rows(
        "SELECT e.*, i.symbol FROM earnings e JOIN instrument i ON i.id=e.instrument_id "
        "JOIN watch w ON w.instrument_id=i.id "
        "WHERE w.active=1 AND e.scheduled_at >= ? AND e.scheduled_at <= ? "
        "ORDER BY e.scheduled_at",
        (now, until),
    )
    return jsonify([{
        "symbol": r["symbol"],
        "scheduled_at": r["scheduled_at"],
        "when_hint": r["when_hint"],
        "eps_estimate": r["eps_estimate"],
        "rev_estimate": r["rev_estimate"],
    } for r in data])


@bp.get("/instrument/<symbol>/earnings")
def per_symbol_earnings(symbol: str):
    inst = one("SELECT id FROM instrument WHERE symbol=?", (symbol.upper(),))
    if inst is None:
        return jsonify({"error": "instrument not found"}), 404
    data = rows(
        "SELECT * FROM earnings WHERE instrument_id=? ORDER BY scheduled_at",
        (inst["id"],),
    )
    return jsonify([{
        "scheduled_at": r["scheduled_at"],
        "when_hint": r["when_hint"],
        "eps_estimate": r["eps_estimate"],
        "rev_estimate": r["rev_estimate"],
    } for r in data])
