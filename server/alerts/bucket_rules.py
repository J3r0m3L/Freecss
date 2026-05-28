"""Bucket-level (factor) alert rules (DESIGN.md §9 "Factor-level deleveraging
alerts (v2)").

For each (watch, bucket) pair that survived BH-FDR (`factor_exposure.significant
= 1`), fire when the bucket's representative ETF moves abnormally hard AND that
move is adverse to the watch's thesis *via the watch's exposure to that bucket*.

Adversity gate from §9:
    sign(β) · sign(bucket_return) · sign(thesis) < 0

i.e. the bucket move, refracted through β onto the watched name, opposes the
user's directional bet. A BULL watch with β=+1 to a sector that drops 3σ → fire.
A BULL watch with β=−1 to the same sector → aligned (the negative exposure
*benefits* from a sector drop) → log-only.

Severity scales with |z|. Defaults follow §9's "fire a warn at |z|>3" plus
reasonable escalation; per-watch overrides not in v2.
"""
from __future__ import annotations

from dataclasses import dataclass

from server.alerts import Severity
from server.alerts.rules import RuleHit

DEFAULT_Z_WARN = 3.0
DEFAULT_Z_HIGH = 4.0
DEFAULT_Z_CRITICAL = 5.0


@dataclass(frozen=True)
class BucketAlertInput:
    bucket_id: int
    bucket_label: str
    rep_symbol: str
    beta: float
    bucket_return: float       # signed decimal (e.g. -0.028)
    z: float                   # signed; sign carries direction of move
    direction: str             # 'BULL' | 'BEAR'  (the watch's thesis)


def _is_adverse(direction: str, beta: float, bucket_return: float) -> bool:
    """sign(β) · sign(bucket_return) · sign(thesis) < 0  → adverse."""
    if beta == 0 or bucket_return == 0:
        return False
    thesis_sign = 1 if direction == "BULL" else -1
    return (1 if beta > 0 else -1) * (1 if bucket_return > 0 else -1) * thesis_sign < 0


def _severity_for(abs_z: float, *, z_warn: float, z_high: float,
                  z_critical: float) -> Severity | None:
    if abs_z >= z_critical:
        return Severity.CRITICAL
    if abs_z >= z_high:
        return Severity.HIGH
    if abs_z >= z_warn:
        return Severity.WARN
    return None


def evaluate_bucket(*, inp: BucketAlertInput,
                    z_warn: float = DEFAULT_Z_WARN,
                    z_high: float = DEFAULT_Z_HIGH,
                    z_critical: float = DEFAULT_Z_CRITICAL) -> RuleHit | None:
    """Build a RuleHit for one (watch, bucket) pair, or None if below threshold.

    The alert `kind` is namespaced as `factor:<bucket_label>` so the engine's
    per-(symbol, kind) dedup naturally separates simultaneous alerts on
    different buckets affecting the same watch.
    """
    sev = _severity_for(abs(inp.z), z_warn=z_warn, z_high=z_high,
                        z_critical=z_critical)
    if sev is None:
        return None
    adverse = _is_adverse(inp.direction, inp.beta, inp.bucket_return)
    return RuleHit(
        kind=f"factor:{inp.bucket_label}",
        severity=sev,
        adverse=adverse,
        payload={
            "bucket_id": inp.bucket_id,
            "bucket_label": inp.bucket_label,
            "rep_symbol": inp.rep_symbol,
            "beta": round(inp.beta, 3),
            "bucket_return": round(inp.bucket_return, 4),
            "z": round(inp.z, 2),
            "thesis": inp.direction,
        },
    )
