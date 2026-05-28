"""Profile-text generation via Claude Haiku (DESIGN.md §3.3, §10.1).

Inputs are deliberately time-invariant — sector / industry / country /
description / display_name — so the resulting paragraph stays valid until the
quarterly meta_refresh changes those fields. Cost: ~$0.005 per call.

A stub generator runs when:
- the `anthropic` SDK is not installed, or
- `ANTHROPIC_API_KEY` is missing, or
- `DW_PROFILE_TEXT_BACKEND=stub` is set (always in the test harness).

The stub returns a deterministic paragraph stitched from the inputs — enough
for FinBERT to embed something coherent. Pipeline integration tests don't
require the real Haiku.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger("deleveraging_watch.nlp.profile_text")

_PROMPT_TEMPLATE = """You are writing a SHORT economic-exposure paragraph for a market-awareness dashboard.

Subject company: {display_name} ({symbol})
Sector: {sector}
Industry: {industry}
Country: {country}
Business description: {description}

Write 4–6 sentences describing this company's macro, regulatory, factor, and geopolitical exposures.
Use vocabulary-rich macro terms where relevant (interest rates, Fed policy, tariffs, antitrust, supply chain, forex, OPEC, EU regulation, etc.).
Avoid: market cap, recent prices, recent events, current executives, anything that changes day-to-day.
Output the paragraph only, no preamble."""


@dataclass(frozen=True)
class ProfileTextResult:
    text: str
    backend: str           # 'haiku' | 'stub' | 'fallback'
    cost_usd: float        # 0.005 for haiku, 0 for stub/fallback


def _format_prompt(meta: dict, *, symbol: str, display_name: str) -> str:
    return _PROMPT_TEMPLATE.format(
        symbol=symbol,
        display_name=display_name or symbol,
        sector=meta.get("sector") or "unknown",
        industry=meta.get("industry") or meta.get("sic_description") or "unknown",
        country=meta.get("country") or "unknown",
        description=(meta.get("description") or "").strip()[:1500] or "unknown",
    )


def _stub_paragraph(meta: dict, *, symbol: str, display_name: str) -> str:
    sector = meta.get("sector") or "general"
    industry = meta.get("industry") or meta.get("sic_description") or "diversified"
    country = meta.get("country") or "US"
    desc = (meta.get("description") or "").strip()
    head = (
        f"{display_name or symbol} operates in the {industry} industry within the "
        f"{sector} sector, headquartered in {country}."
    )
    factor = (
        f"As a {sector.lower()} name it is sensitive to interest rates, broad "
        "equity-market beta, and policy shifts that affect its industry "
        "(antitrust, tariffs, regulation)."
    )
    macro = (
        "Cross-border revenue exposure introduces forex translation effects and "
        "geopolitical risk; supply-chain frictions and energy prices feed through "
        "into input costs."
    )
    business = desc[:600] if desc else (
        f"The firm's principal activities place it among other {industry} peers."
    )
    return " ".join([head, factor, macro, business])


def generate_profile_text(*, symbol: str, display_name: str, meta: dict) -> ProfileTextResult:
    """Call Haiku to write the exposure paragraph, with stub/fallback safety nets."""
    backend = os.environ.get("DW_PROFILE_TEXT_BACKEND", "auto")
    if backend == "stub":
        return ProfileTextResult(
            text=_stub_paragraph(meta, symbol=symbol, display_name=display_name),
            backend="stub", cost_usd=0.0,
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.info("ANTHROPIC_API_KEY missing; using stub profile_text for %s", symbol)
        return ProfileTextResult(
            text=_stub_paragraph(meta, symbol=symbol, display_name=display_name),
            backend="stub", cost_usd=0.0,
        )

    try:  # pragma: no cover — requires network + anthropic SDK installed
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        prompt = _format_prompt(meta, symbol=symbol, display_name=display_name)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in resp.content if hasattr(block, "text")).strip()
        if not text:
            raise RuntimeError("haiku returned empty content")
        return ProfileTextResult(text=text, backend="haiku", cost_usd=0.005)
    except Exception as exc:  # noqa: BLE001
        log.warning("Haiku profile_text failed for %s (%s); falling back to description", symbol, exc)
        # Fallback per §10.1: embed Finnhub description directly.
        text = (meta.get("description") or "").strip() or _stub_paragraph(
            meta, symbol=symbol, display_name=display_name,
        )
        return ProfileTextResult(text=text, backend="fallback", cost_usd=0.0)
