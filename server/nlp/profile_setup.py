"""Profile setup pipeline (DESIGN.md §10.1).

Pull meta from Finnhub → write meta_json → Haiku-write profile_text → FinBERT-
embed → persist. One call wraps the whole pipeline for an instrument; runs
synchronously on watchlist-add (~1–2s wall-clock when both APIs are present).

Failure modes are belt-and-suspenders: profile_text falls back to a stub on
Anthropic outage, and FinBERT's stub backend means we always end with a
populated profile_embedding even with zero credentials configured.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from server.adapters.finnhub import fetch_profile
from server.db import execute, one
from server.nlp.profile_embed import embed_and_persist
from server.nlp.profile_text import generate_profile_text

log = logging.getLogger("deleveraging_watch.nlp.profile_setup")


def setup_profile(instrument_id: int) -> None:
    """Refresh meta + profile_text + profile_embedding for one instrument.

    Idempotent: safe to call repeatedly. The monthly refresh job re-uses this.
    """
    inst = one("SELECT id, symbol, display_name, meta_json FROM instrument WHERE id=?",
               (instrument_id,))
    if not inst:
        log.warning("profile_setup: instrument_id=%s not found", instrument_id)
        return

    symbol = inst["symbol"]
    fh = fetch_profile(symbol)
    meta = json.loads(inst["meta_json"]) if inst["meta_json"] else {}
    meta.update(fh.to_meta_dict())

    execute(
        "UPDATE instrument SET meta_json=?, meta_refreshed_at=? WHERE id=?",
        (json.dumps(meta), datetime.now(timezone.utc).isoformat(), instrument_id),
    )

    txt = generate_profile_text(
        symbol=symbol, display_name=inst["display_name"] or symbol, meta=meta,
    )
    embed_and_persist(instrument_id, txt.text)
    log.info("profile_setup complete for %s (backend=%s)", symbol, txt.backend)
