"""threshold_evaluator (§7.3) — every 5s, walk active watches and fire any
price/volume/spread/combined rule hits through the alert engine (§8)."""
from __future__ import annotations

from server.alerts import engine
from server.alerts.rules import evaluate
from server.db import get_setting, rows
from server.jobs import record_run


def run() -> None:
    from server.app import socketio  # late import: app/socketio exist by run time

    with record_run("threshold_evaluator") as result:
        settings = (get_setting("global", {}) or {}).get("thresholds", {})
        watches = rows(
            "SELECT w.id, w.instrument_id, w.direction, w.px_jump_pct, "
            "       w.px_jump_window_s, w.spread_bps_max, w.volume_zscore, i.symbol "
            "FROM watch w JOIN instrument i ON i.id=w.instrument_id WHERE w.active=1"
        )
        fired = 0
        for w in watches:
            for hit in evaluate(w, settings):
                aid = engine.fire(
                    instrument_id=w["instrument_id"], symbol=w["symbol"],
                    direction=w["direction"], hit=hit, socketio=socketio,
                )
                if aid is not None:
                    fired += 1
        result["rows"] = fired
