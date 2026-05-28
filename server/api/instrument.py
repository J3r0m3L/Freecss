"""Instrument drill-down detail + chart bars (DESIGN.md §7.1).

Phase 0 returns the live snapshot and 1m bars. Phase 3 adds the Context-tab
factor-exposures endpoint. Microstructure / Notes tabs land in later phases.
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


@bp.get("/instrument/<symbol>/exposures")
def exposures(symbol: str):
    """Phase 3 Context tab. Returns factor_exposure rows joined with bucket info.

    Default `significant_only=true` filters to BH-FDR-survivors (§9). Pass
    `significant_only=false` to see all 80 buckets.
    """
    symbol = symbol.upper()
    inst = one("SELECT id FROM instrument WHERE symbol=?", (symbol,))
    if inst is None:
        return jsonify({"error": "instrument not found"}), 404
    watch = one("SELECT id FROM watch WHERE instrument_id=? AND active=1",
                (inst["id"],))
    if watch is None:
        return jsonify({"error": f"{symbol} is not on an active watch"}), 404

    significant_only = (request.args.get("significant_only", "true").lower() == "true")
    base = (
        "SELECT b.id AS bucket_id, b.label AS bucket_label, b.kind AS bucket_kind, "
        "       b.pc1_var_explained, ri.symbol AS rep_symbol, "
        "       fe.beta, fe.intercept, fe.r_squared, fe.p_value, fe.q_value, "
        "       fe.significant, fe.correlation, fe.last_residual, fe.window_days, "
        "       fe.computed_at "
        "FROM factor_exposure fe "
        "JOIN factor_bucket b ON b.id = fe.bucket_id "
        "JOIN instrument ri  ON ri.id = b.representative_id "
        "WHERE fe.watch_id=?"
    )
    params: tuple = (watch["id"],)
    if significant_only:
        base += " AND fe.significant=1"
    base += " ORDER BY ABS(fe.beta) DESC"
    data = rows(base, params)

    return jsonify({
        "symbol": symbol,
        "watch_id": watch["id"],
        "significant_only": significant_only,
        "exposures": [{
            "bucket_id": r["bucket_id"],
            "bucket_label": r["bucket_label"],
            "bucket_kind": r["bucket_kind"],
            "representative": r["rep_symbol"],
            "pc1_var_explained": r["pc1_var_explained"],
            "beta": r["beta"],
            "intercept": r["intercept"],
            "r_squared": r["r_squared"],
            "p_value": r["p_value"],
            "q_value": r["q_value"],
            "significant": bool(r["significant"]),
            "correlation": r["correlation"],
            "last_residual": r["last_residual"],
            "window_days": r["window_days"],
            "computed_at": r["computed_at"],
        } for r in data],
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
