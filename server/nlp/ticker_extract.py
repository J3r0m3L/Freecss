"""Ticker extraction (DESIGN.md §10.2, §10.3).

Used to catch tickers Massive didn't tag in `news.tickers[]` and to extract
tickers from X tweet bodies. Conservative: we only match symbols that look like
real tickers (1–5 uppercase letters, optional `.X` class suffix), and we cross-
check against the active watchlist so we don't surface spurious words like
"FREE" or "I" as tickers.

Patterns recognized:
- `$AAPL`, `$BRK.B`           — cashtags (X convention)
- standalone `AAPL` / `BRK.B` — only if matched against the watchlist whitelist

A union helper merges these with whatever Massive returned in news.tickers[].
"""
from __future__ import annotations

import re
from typing import Iterable

_CASHTAG_RE = re.compile(r"\$([A-Z][A-Z0-9]{0,4}(?:\.[A-Z])?)\b")
_WORD_RE = re.compile(r"\b([A-Z][A-Z0-9]{0,4}(?:\.[A-Z])?)\b")


def extract_tickers(text: str, *, watchlist: Iterable[str] = ()) -> list[str]:
    """Return tickers found in `text`.

    Cashtag matches (`$AAPL`) always pass — they're unambiguous.
    Bare-uppercase matches require membership in `watchlist` to count, because
    English words like "GDP", "CPI", "AI" are valid prose but not what we want.
    Output is ordered by first appearance and deduped.
    """
    if not text:
        return []
    seen: dict[str, None] = {}
    wl = {w.upper() for w in watchlist}

    for m in _CASHTAG_RE.finditer(text):
        sym = m.group(1).upper()
        seen.setdefault(sym, None)

    if wl:
        for m in _WORD_RE.finditer(text):
            sym = m.group(1).upper()
            if sym in wl:
                seen.setdefault(sym, None)

    return list(seen.keys())


def union_tickers(
    massive_tickers: Iterable[str], text: str, *, watchlist: Iterable[str] = ()
) -> list[str]:
    """Merge Massive's tagged tickers with regex extraction; preserve order."""
    seen: dict[str, None] = {}
    for sym in massive_tickers or ():
        if sym:
            seen.setdefault(sym.upper(), None)
    for sym in extract_tickers(text, watchlist=watchlist):
        seen.setdefault(sym, None)
    return list(seen.keys())
