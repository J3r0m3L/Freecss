"""Persist profile_text → FinBERT embedding → instrument.profile_embedding.

Called from the watchlist-add path (§10.1) and the monthly
`profile_text_refresh` job. One-shot; no streaming.
"""
from __future__ import annotations

import logging

from server.db import execute
from server.nlp.finbert import embedding_to_blob, get_finbert

log = logging.getLogger("deleveraging_watch.nlp.profile_embed")


def embed_and_persist(instrument_id: int, profile_text: str) -> list[float]:
    """Run FinBERT on `profile_text`, write the BLOB, return the vector."""
    result = get_finbert().score(profile_text or "")
    blob = embedding_to_blob(result.embedding)
    execute(
        "UPDATE instrument SET profile_text=?, profile_embedding=? WHERE id=?",
        (profile_text, blob, instrument_id),
    )
    log.info("profile_embedding persisted for instrument_id=%s", instrument_id)
    return result.embedding
