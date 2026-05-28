"""Watchlist CRUD (DESIGN.md §7.1).

Phase 0: adding a symbol creates a bare instrument row if absent. The Massive
ticker-reference + Finnhub /stock/profile2 enrichment (sector/industry/cap/logo
+ profile_text/embedding) lands in Phase 2; until then meta_json stays null and
display_name defaults to the symbol.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from server import state
from server.db import execute, one, rows
from server.feed import feed

bp = Blueprint("watchlist", __name__, url_prefix="/api")

_VALID_DIRECTIONS = {"BULL", "BEAR"}
_THRESHOLD_FIELDS = ("px_jump_pct", "px_jump_window_s", "spread_bps_max",
                     "volume_zscore", "position_size")


def _snapshot(symbol: str) -> dict | None:
    q = state.latest(symbol)
    if q is None:
        return None
    return {"ts": q.ts.isoformat(), "bid": q.bid, "ask": q.ask, "last": q.last,
            "bid_size": q.bid_size, "ask_size": q.ask_size}


def _watch_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "symbol": r["symbol"],
        "display_name": r["display_name"],
        "asset_class": r["asset_class"],
        "direction": r["direction"],
        "active": bool(r["active"]),
        "entered_at": r["entered_at"],
        "thresholds": {f: r[f] for f in _THRESHOLD_FIELDS},
        "snapshot": _snapshot(r["symbol"]),
    }


@bp.get("/watchlist")
def list_watchlist():
    data = rows(
        "SELECT w.id, w.direction, w.active, w.entered_at, "
        "       w.px_jump_pct, w.px_jump_window_s, w.spread_bps_max, "
        "       w.volume_zscore, w.position_size, "
        "       i.symbol, i.display_name, i.asset_class "
        "FROM watch w JOIN instrument i ON i.id=w.instrument_id "
        "WHERE w.active=1 ORDER BY i.symbol"
    )
    return jsonify([_watch_view(r) for r in data])


@bp.post("/watchlist")
def add_watch():
    body = request.get_json(silent=True) or {}
    symbol = (body.get("symbol") or "").strip().upper()
    direction = (body.get("direction") or "").strip().upper()
    if not symbol:
        return jsonify({"error": "symbol is required"}), 400
    if direction not in _VALID_DIRECTIONS:
        return jsonify({"error": "direction must be BULL or BEAR"}), 400

    inst = one("SELECT * FROM instrument WHERE symbol=?", (symbol,))
    if inst is None:
        cur = execute(
            "INSERT INTO instrument(symbol, display_name, asset_class, data_adapter) "
            "VALUES(?,?,?,?)",
            (symbol, symbol, body.get("asset_class", "equity"), "massive"),
        )
        instrument_id = cur.lastrowid
    else:
        instrument_id = inst["id"]

    existing = one(
        "SELECT id, active FROM watch WHERE instrument_id=? ORDER BY id DESC LIMIT 1",
        (instrument_id,),
    )
    thresholds = {f: body.get("thresholds", {}).get(f) for f in _THRESHOLD_FIELDS}
    if existing and existing["active"]:
        return jsonify({"error": f"{symbol} is already on the watchlist"}), 409
    if existing:  # reactivate a soft-deleted watch
        execute("UPDATE watch SET active=1, direction=? WHERE id=?",
                (direction, existing["id"]))
        watch_id = existing["id"]
    else:
        cur = execute(
            "INSERT INTO watch(instrument_id, direction, px_jump_pct, px_jump_window_s, "
            "spread_bps_max, volume_zscore, position_size) VALUES(?,?,?,?,?,?,?)",
            (instrument_id, direction, thresholds["px_jump_pct"],
             thresholds["px_jump_window_s"], thresholds["spread_bps_max"],
             thresholds["volume_zscore"], thresholds["position_size"]),
        )
        watch_id = cur.lastrowid

    feed.ensure_symbol(symbol, instrument_id)
    r = one(
        "SELECT w.id, w.direction, w.active, w.entered_at, w.px_jump_pct, "
        "w.px_jump_window_s, w.spread_bps_max, w.volume_zscore, w.position_size, "
        "i.symbol, i.display_name, i.asset_class "
        "FROM watch w JOIN instrument i ON i.id=w.instrument_id WHERE w.id=?",
        (watch_id,),
    )
    return jsonify(_watch_view(r)), 201


@bp.patch("/watchlist/<int:watch_id>")
def update_watch(watch_id: int):
    body = request.get_json(silent=True) or {}
    if not one("SELECT 1 FROM watch WHERE id=?", (watch_id,)):
        return jsonify({"error": "watch not found"}), 404

    sets, params = [], []
    if "direction" in body:
        d = (body["direction"] or "").upper()
        if d not in _VALID_DIRECTIONS:
            return jsonify({"error": "direction must be BULL or BEAR"}), 400
        sets.append("direction=?")
        params.append(d)
    for f in _THRESHOLD_FIELDS:
        if f in body.get("thresholds", {}):
            sets.append(f"{f}=?")
            params.append(body["thresholds"][f])
    if not sets:
        return jsonify({"error": "nothing to update"}), 400
    params.append(watch_id)
    execute(f"UPDATE watch SET {', '.join(sets)} WHERE id=?", tuple(params))
    return jsonify({"ok": True})


@bp.delete("/watchlist/<int:watch_id>")
def delete_watch(watch_id: int):
    if not one("SELECT 1 FROM watch WHERE id=?", (watch_id,)):
        return jsonify({"error": "watch not found"}), 404
    execute("UPDATE watch SET active=0 WHERE id=?", (watch_id,))
    return jsonify({"ok": True})
