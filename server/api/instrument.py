"""Instrument drill-down detail + chart bars (DESIGN.md §7.1).

Phase 0 returns the live snapshot and 1m bars. The Microstructure/Context/News/
Notes/Earnings tabs (§11.C) are populated in later phases.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from server import state
from server.db import one, rows

bp = Blueprint("instrument", __name__, url_prefix="/api")


@bp.get("/instrument/<symbol>")
def detail(symbol: str):
    symbol = symbol.upper()
    inst = one("SELECT * FROM instrument WHERE symbol=?", (symbol,))
    if inst is None:
        return jsonify({"error": "instrument not found"}), 404
    watch = one(
        "SELECT id, direction, active, position_size FROM watch "
        "WHERE instrument_id=? AND active=1",
        (inst["id"],),
    )
    q = state.latest(symbol)
    return jsonify({
        "symbol": inst["symbol"],
        "display_name": inst["display_name"],
        "asset_class": inst["asset_class"],
        "exchange": inst["exchange"],
        "meta": json.loads(inst["meta_json"]) if inst["meta_json"] else None,
        "meta_refreshed_at": inst["meta_refreshed_at"],
        "watch": watch,
        "snapshot": None if q is None else {
            "ts": q.ts.isoformat(), "bid": q.bid, "ask": q.ask, "last": q.last,
            "bid_size": q.bid_size, "ask_size": q.ask_size,
        },
    })


@bp.get("/instrument/<symbol>/bars")
def bars(symbol: str):
    symbol = symbol.upper()
    inst = one("SELECT id FROM instrument WHERE symbol=?", (symbol,))
    if inst is None:
        return jsonify({"error": "instrument not found"}), 404
    tf = request.args.get("tf", "1m")
    if tf != "1m":
        return jsonify({"error": "Phase 0 serves tf=1m only"}), 400
    frm = request.args.get("from")
    if frm:
        since = frm
    else:
        since = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    data = rows(
        "SELECT ts, o, h, l, c, v, vwap FROM bar_1m "
        "WHERE instrument_id=? AND ts >= ? ORDER BY ts",
        (inst["id"], since),
    )
    return jsonify({"symbol": symbol, "tf": tf, "bars": data})
