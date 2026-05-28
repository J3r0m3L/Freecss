"""tick_aggregator (§7.3) — roll the last minute of ticks into a bar_1m row per
active instrument. Phase 0 uses `last` as the price series; Phase 1's real trade
stream will refine OHLCV/VWAP."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from server.db import get_db, rows
from server.jobs import record_run


def run() -> None:
    with record_run("tick_aggregator") as result:
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        window_start = now - timedelta(minutes=1)
        db = get_db()
        written = 0
        for inst in rows("SELECT DISTINCT instrument_id FROM watch WHERE active=1"):
            iid = inst["instrument_id"]
            tr = db.execute(
                "SELECT last, trade_size FROM tick "
                "WHERE instrument_id=? AND ts >= ? AND ts < ? ORDER BY ts",
                (iid, window_start.isoformat(), now.isoformat()),
            ).fetchall()
            prices = [row["last"] for row in tr if row["last"] is not None]
            if not prices:
                continue
            vol = sum((row["trade_size"] or 0) for row in tr)
            o, c = prices[0], prices[-1]
            h, low = max(prices), min(prices)
            vwap = sum(prices) / len(prices)
            db.execute(
                "INSERT OR REPLACE INTO bar_1m(instrument_id, ts, o, h, l, c, v, vwap) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (iid, window_start.isoformat(), o, h, low, c, vol, round(vwap, 4)),
            )
            written += 1
        db.commit()
        result["rows"] = written
