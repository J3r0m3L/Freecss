"""Alert rule evaluation (DESIGN.md §8).

Pure-ish computation: given a watch and recent market data from the `tick` /
`bar_1m` tables, produce candidate `RuleHit`s. Orchestration (dedup, persistence,
notification, quiet-hours routing) lives in engine.py.

Adverse model (synthesising §1 + §8): the *price move* is the directional
trigger. A move opposite the thesis is `adverse`. Spread and volume are
*confirming* microstructure — they only page when accompanied by an adverse
price move (which is exactly the forced-unwind signature in §1). Threshold
breaches that are aligned with the thesis are still recorded (adverse=0) but do
not page, per §1 "aligned moves are still logged but do not page."
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from server.alerts import Severity
from server.analytics.volume import volume_zscore
from server.db import get_db

# Default thresholds (§8). Per-watch overrides take precedence; global settings
# override these baseline constants.
DEFAULTS = {
    "px_jump_pct": 0.03,
    "px_jump_window_s": 300,
    "spread_bps_max": 50.0,
    "volume_zscore": 3.0,
}

_SPREAD_SUSTAIN_S = 30  # spread must hold above threshold this long (§8)

_SEVERITY_ORDER = {Severity.INFO: 0, Severity.WARN: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}


def severity_rank(s: Severity) -> int:
    return _SEVERITY_ORDER[s]


@dataclass
class RuleHit:
    kind: str
    severity: Severity
    adverse: bool
    payload: dict = field(default_factory=dict)


def _is_adverse(direction: str, signed_return: float) -> bool:
    if direction == "BULL":
        return signed_return < 0
    return signed_return > 0  # BEAR


def _ticks_since(instrument_id: int, seconds: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    return [dict(r) for r in get_db().execute(
        "SELECT ts, bid, ask, last FROM tick WHERE instrument_id=? AND ts >= ? ORDER BY ts",
        (instrument_id, cutoff),
    ).fetchall()]


def _threshold(watch: dict, key: str, settings: dict) -> float:
    if watch.get(key) is not None:
        return watch[key]
    return settings.get(key, DEFAULTS[key])


def evaluate(watch: dict, settings: dict | None = None) -> list[RuleHit]:
    """Evaluate all price/volume/spread rules for one active watch."""
    settings = settings or {}
    iid = watch["instrument_id"]
    direction = watch["direction"]
    window_s = int(_threshold(watch, "px_jump_window_s", settings))

    ticks = _ticks_since(iid, window_s)
    prices = [t["last"] for t in ticks if t["last"] is not None]
    if len(prices) < 2:
        return []

    p0, p1 = prices[0], prices[-1]
    if p0 <= 0:
        return []
    pct = (p1 - p0) / p0
    adverse = _is_adverse(direction, pct)

    hits: list[RuleHit] = []
    px_hit = _price_jump(watch, settings, pct, adverse)
    if px_hit:
        hits.append(px_hit)
    spread_hit = _spread(watch, settings, ticks, adverse)
    if spread_hit:
        hits.append(spread_hit)
    vol_hit = _volume(watch, settings, iid, adverse)
    if vol_hit:
        hits.append(vol_hit)

    # Combined deleveraging signal: adverse price jump + volume z>3 (§8) → critical.
    if adverse and px_hit and vol_hit and (vol_hit.payload.get("z", 0) > 3):
        hits.append(RuleHit(
            kind="combined", severity=Severity.CRITICAL, adverse=True,
            payload={"pct": pct, "z": vol_hit.payload.get("z"),
                     "note": "adverse price jump confirmed by volume spike"},
        ))
    return hits


def _price_jump(watch: dict, settings: dict, pct: float, adverse: bool) -> RuleHit | None:
    warn_th = _threshold(watch, "px_jump_pct", settings)
    a = abs(pct)
    if a < warn_th:
        return None
    if a >= 0.07:
        sev = Severity.CRITICAL
    elif a >= 0.05:
        sev = Severity.HIGH
    else:
        sev = Severity.WARN
    return RuleHit(kind="px_jump", severity=sev, adverse=adverse,
                   payload={"pct": pct, "threshold": warn_th})


def _spread(watch: dict, settings: dict, ticks: list[dict], adverse: bool) -> RuleHit | None:
    max_bps = _threshold(watch, "spread_bps_max", settings)
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=_SPREAD_SUSTAIN_S)).isoformat()
    recent = [t for t in ticks if t["ts"] >= cutoff
              and t["bid"] and t["ask"] and t["last"]]
    if len(recent) < 2:
        return None
    bps = [((t["ask"] - t["bid"]) / t["last"]) * 10_000 for t in recent if t["last"] > 0]
    if not bps or min(bps) <= max_bps:  # sustained = every recent sample over threshold
        return None
    cur = bps[-1]
    if cur > 150:
        sev = Severity.CRITICAL
    elif cur > 100:
        sev = Severity.HIGH
    else:
        sev = Severity.WARN
    return RuleHit(kind="spread", severity=sev, adverse=adverse,
                   payload={"spread_bps": round(cur, 1), "threshold": max_bps})


def _volume(watch: dict, settings: dict, instrument_id: int, adverse: bool) -> RuleHit | None:
    z_th = _threshold(watch, "volume_zscore", settings)
    vz = volume_zscore(instrument_id)
    if vz is None or vz.z < z_th:
        return None
    if vz.z > 5:
        sev = Severity.CRITICAL
    elif vz.z > 4:
        sev = Severity.HIGH
    else:
        sev = Severity.WARN
    return RuleHit(kind="volume", severity=sev, adverse=adverse,
                   payload={"z": round(vz.z, 2), "threshold": z_th,
                            "baseline_mean": round(vz.baseline_mean, 1),
                            "n_samples": vz.n_samples})
