"""Intraday residual computation (DESIGN.md §9).

For today's session per (watch, bucket):
    expected = α + β · r_rep_today
    residual = r_symbol_today − expected

`r_today` is computed live from the last `bar_1m` close vs the prior session's
daily close (i.e. open-to-now intraday return). This is the bit that drives the
"the stock is moving against you for reasons that aren't 'the whole sector is
moving'" callout on the Context tab.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from server.db import one

log = logging.getLogger("deleveraging_watch.analytics.residual")


@dataclass(frozen=True)
class IntradayMove:
    instrument_id: int
    prev_close: float | None
    last_price: float | None

    @property
    def return_pct(self) -> float | None:
        if self.prev_close is None or self.last_price is None:
            return None
        if self.prev_close <= 0:
            return None
        return (self.last_price - self.prev_close) / self.prev_close


def latest_intraday_move(instrument_id: int) -> IntradayMove:
    """Most-recent bar_1m close vs the prior session's daily close."""
    prev = one(
        "SELECT c FROM bar_daily WHERE instrument_id=? ORDER BY date DESC LIMIT 1",
        (instrument_id,),
    )
    last = one(
        "SELECT c FROM bar_1m WHERE instrument_id=? ORDER BY ts DESC LIMIT 1",
        (instrument_id,),
    )
    return IntradayMove(
        instrument_id=instrument_id,
        prev_close=(prev or {}).get("c"),
        last_price=(last or {}).get("c"),
    )


def residual(*, alpha: float, beta: float, watch_id: int, rep_id: int) -> float | None:
    """Today's idiosyncratic residual; None if either side has no intraday move."""
    rep_move = latest_intraday_move(rep_id).return_pct
    watch_move = latest_intraday_move(watch_id).return_pct
    if rep_move is None or watch_move is None:
        return None
    expected = alpha + beta * rep_move
    return watch_move - expected
