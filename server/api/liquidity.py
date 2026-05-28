"""GET /api/instrument/<symbol>/liquidity (DESIGN.md §7.1, §11.C).

Reads the latest `liquidity_daily` row for the symbol and overlays the
exit-liquidity calc when the corresponding watch has `position_size` set.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from server.analytics.liquidity import exit_liquidity, liquidity_rank
from server.db import one

bp = Blueprint("liquidity", __name__, url_prefix="/api")

_DEFAULT_PARTICIPATION = 0.10


@bp.get("/instrument/<symbol>/liquidity")
def liquidity(symbol: str):
    symbol = symbol.upper()
    inst = one("SELECT id FROM instrument WHERE symbol=?", (symbol,))
    if inst is None:
        return jsonify({"error": "instrument not found"}), 404
    participation = float(request.args.get("participation", _DEFAULT_PARTICIPATION))

    snap = one(
        "SELECT date, adv_shares_21d, adv_dollar_21d, spread_avg_bps, "
        "       pct_zero_volume, computed_at "
        "FROM liquidity_daily WHERE instrument_id=? ORDER BY date DESC LIMIT 1",
        (inst["id"],),
    )
    watch = one(
        "SELECT id, position_size FROM watch WHERE instrument_id=? AND active=1",
        (inst["id"],),
    )

    rank_tuple = liquidity_rank(inst["id"])
    body: dict = {
        "symbol": symbol,
        "computed_at": (snap or {}).get("computed_at"),
        "as_of": (snap or {}).get("date"),
        "adv_shares_21d": (snap or {}).get("adv_shares_21d"),
        "adv_dollar_21d": (snap or {}).get("adv_dollar_21d"),
        "spread_avg_bps": (snap or {}).get("spread_avg_bps"),
        "pct_zero_volume": (snap or {}).get("pct_zero_volume"),
        "participation": participation,
        "position_size": (watch or {}).get("position_size"),
        "rank_in_watchlist": rank_tuple[0] if rank_tuple else None,
        "watchlist_size": rank_tuple[1] if rank_tuple else None,
        "days_to_exit": None,
        "cost_to_exit_bps": None,
    }
    if watch and watch.get("position_size"):
        exit_ = exit_liquidity(
            position_size=watch["position_size"],
            adv_shares=(snap or {}).get("adv_shares_21d"),
            spread_bps=(snap or {}).get("spread_avg_bps"),
            participation=participation,
        )
        body["days_to_exit"] = exit_.days_to_exit
        body["cost_to_exit_bps"] = exit_.cost_to_exit_bps

    return jsonify(body)
