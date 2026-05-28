"""Alert history + acknowledgement (DESIGN.md §7.1)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from server.db import execute, one, rows

bp = Blueprint("alerts", __name__, url_prefix="/api")


def _view(r: dict) -> dict:
    return {
        "id": r["id"],
        "symbol": r["symbol"],
        "kind": r["kind"],
        "severity": r["severity"],
        "adverse": bool(r["adverse"]),
        "ts": r["ts"],
        "payload": json.loads(r["payload_json"]) if r["payload_json"] else {},
        "notified_via": r["notified_via"],
        "acked_at": r["acked_at"],
        "quiet_queued": bool(r["quiet_queued"]),
    }


@bp.get("/alerts")
def list_alerts():
    since = request.args.get("since")
    limit = min(int(request.args.get("limit", 100)), 500)
    if since:
        data = rows(
            "SELECT a.*, i.symbol FROM alert a JOIN instrument i ON i.id=a.instrument_id "
            "WHERE a.ts >= ? ORDER BY a.ts DESC LIMIT ?",
            (since, limit),
        )
    else:
        data = rows(
            "SELECT a.*, i.symbol FROM alert a JOIN instrument i ON i.id=a.instrument_id "
            "ORDER BY a.ts DESC LIMIT ?",
            (limit,),
        )
    return jsonify([_view(r) for r in data])


@bp.post("/alerts/<int:alert_id>/ack")
def ack_alert(alert_id: int):
    if not one("SELECT 1 FROM alert WHERE id=?", (alert_id,)):
        return jsonify({"error": "alert not found"}), 404
    execute("UPDATE alert SET acked_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), alert_id))
    return jsonify({"ok": True})
