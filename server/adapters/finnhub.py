"""Finnhub adapter (DESIGN.md §3.1, §10.1, §7.3).

Used for two unrelated jobs:
- Profile metadata: GET /stock/profile2?symbol=X  → sector, industry, country,
  description, logo, IPO date, market cap (not used in profile_text).
- Earnings calendar: GET /calendar/earnings?from=...&to=...&symbol=X

Falls back to deterministic stubs when FINNHUB_API_KEY is missing.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone

import requests

log = logging.getLogger("deleveraging_watch.adapters.finnhub")

_PROFILE_URL = "https://finnhub.io/api/v1/stock/profile2"
_EARNINGS_URL = "https://finnhub.io/api/v1/calendar/earnings"
_TIMEOUT_S = 10


def _api_key() -> str:
    return os.environ.get("FINNHUB_API_KEY", "")


@dataclass(frozen=True)
class FinnhubProfile:
    sector: str | None
    industry: str | None
    country: str | None
    market_cap_m: float | None
    ipo_date: str | None
    logo_url: str | None
    website: str | None
    description: str | None

    def to_meta_dict(self) -> dict:
        d = {
            "sector": self.sector,
            "industry": self.industry,
            "country": self.country,
            "market_cap_m": self.market_cap_m,
            "ipo_date": self.ipo_date,
            "logo_url": self.logo_url,
            "website": self.website,
            "description": self.description,
        }
        return {k: v for k, v in d.items() if v is not None}


def _stub_profile(symbol: str) -> FinnhubProfile:
    return FinnhubProfile(
        sector="Technology", industry="Software", country="US",
        market_cap_m=10_000.0, ipo_date="2000-01-01",
        logo_url=None, website=None,
        description=f"{symbol} is a stubbed profile used when FINNHUB_API_KEY is missing.",
    )


def fetch_profile(symbol: str) -> FinnhubProfile:
    key = _api_key()
    if not key:
        log.debug("FINNHUB_API_KEY missing; returning stub profile for %s", symbol)
        return _stub_profile(symbol)
    try:
        resp = requests.get(_PROFILE_URL, params={"symbol": symbol, "token": key},
                            timeout=_TIMEOUT_S)
        resp.raise_for_status()
        d = resp.json() or {}
    except Exception as exc:  # noqa: BLE001
        log.warning("finnhub profile failed for %s: %s", symbol, exc)
        return _stub_profile(symbol)
    return FinnhubProfile(
        sector=d.get("finnhubIndustry") and d.get("ggroup") or d.get("gsector"),
        industry=d.get("finnhubIndustry"),
        country=d.get("country"),
        market_cap_m=d.get("marketCapitalization"),
        ipo_date=d.get("ipo"),
        logo_url=d.get("logo"),
        website=d.get("weburl"),
        description=d.get("name"),  # Finnhub profile2 doesn't carry a long description;
                                    # full text comes from Massive ticker reference.
    )


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    scheduled_at: datetime          # UTC; combines `date` + `hour` (when_hint) if present
    when_hint: str | None           # 'bmo' | 'amc' | 'dmt' | None
    eps_estimate: float | None
    rev_estimate: float | None


def _stub_earnings(symbols: list[str]) -> list[EarningsEvent]:
    """One event per symbol, dated tomorrow at 09:00 UTC."""
    today = datetime.now(timezone.utc)
    return [
        EarningsEvent(
            symbol=s,
            scheduled_at=today.replace(hour=13, minute=0, second=0, microsecond=0),
            when_hint="bmo", eps_estimate=None, rev_estimate=None,
        )
        for s in symbols
    ]


def fetch_earnings(symbols: list[str], *, frm: date, to: date) -> list[EarningsEvent]:
    """Pull earnings for any of `symbols` between [frm, to]. Free tier supports symbol filter."""
    key = _api_key()
    if not key:
        return _stub_earnings(symbols)

    out: list[EarningsEvent] = []
    # Finnhub's calendar endpoint returns a list across all symbols if `symbol` is omitted;
    # passing it per-symbol keeps the response narrow.
    for sym in symbols:
        try:
            resp = requests.get(
                _EARNINGS_URL,
                params={"from": frm.isoformat(), "to": to.isoformat(),
                        "symbol": sym, "token": key},
                timeout=_TIMEOUT_S,
            )
            resp.raise_for_status()
            data = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("finnhub earnings failed for %s: %s", sym, exc)
            continue
        for row in data.get("earningsCalendar", []) or []:
            try:
                d = row.get("date") or ""
                when = (row.get("hour") or "").lower() or None
                # bmo ≈ before market open (~13:00 UTC); amc ≈ after market close (~22:00 UTC);
                # dmt = during market trading.
                hr = {"bmo": 13, "dmt": 17, "amc": 22}.get(when or "", 13)
                scheduled = datetime.fromisoformat(d).replace(
                    hour=hr, tzinfo=timezone.utc,
                )
                out.append(EarningsEvent(
                    symbol=row.get("symbol") or sym,
                    scheduled_at=scheduled,
                    when_hint=when,
                    eps_estimate=row.get("epsEstimate"),
                    rev_estimate=row.get("revenueEstimate"),
                ))
            except Exception:  # noqa: BLE001
                log.exception("could not parse earnings row for %s", sym)
    return out
