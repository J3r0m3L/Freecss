"""bucket_alerts (Phase 5 — DESIGN.md §9 "Factor-level deleveraging alerts").

Every 60s during the session:
1. For each active bucket with a representative, compute today's intraday
   z-score of the rep ETF return (vs trailing 60d daily returns).
2. For each BH-FDR-significant (watch, bucket) exposure: check if the bucket's
   move, refracted through β, is adverse to the watch's thesis.
3. If adverse AND |z| ≥ threshold, fire through the standard engine — same
   dedup, persistence, broadcast, and routing as every other alert kind.

Gate: `setting('global').bucket_alerts.enabled` (default **true**).
Thresholds: `bucket_alerts.z_warn` / `.z_high` / `.z_critical` (overridable in
Settings; sensible defaults from bucket_rules.DEFAULT_*).
"""
from __future__ import annotations

import logging

from server.alerts import engine
from server.alerts.bucket_rules import (
    DEFAULT_Z_CRITICAL, DEFAULT_Z_HIGH, DEFAULT_Z_WARN,
    BucketAlertInput, evaluate_bucket,
)
from server.analytics.bucket_zscore import bucket_zscore
from server.db import get_setting, rows
from server.jobs import record_run

log = logging.getLogger("deleveraging_watch.jobs.bucket_alerts")


def _settings() -> dict:
    cfg = ((get_setting("global", {}) or {}).get("bucket_alerts") or {})
    return {
        "enabled": cfg.get("enabled", True),  # ON by default (Phase 5 choice)
        "z_warn": float(cfg.get("z_warn", DEFAULT_Z_WARN)),
        "z_high": float(cfg.get("z_high", DEFAULT_Z_HIGH)),
        "z_critical": float(cfg.get("z_critical", DEFAULT_Z_CRITICAL)),
    }


def _significant_exposures() -> list[dict]:
    """One row per (watch, bucket) that survived BH-FDR + has a live rep."""
    return rows(
        "SELECT fe.watch_id, fe.bucket_id, fe.beta, "
        "       w.instrument_id AS watch_iid, w.direction, "
        "       wi.symbol AS watch_symbol, "
        "       b.label AS bucket_label, b.representative_id, "
        "       ri.symbol AS rep_symbol "
        "FROM factor_exposure fe "
        "JOIN watch w  ON w.id  = fe.watch_id "
        "JOIN instrument wi ON wi.id = w.instrument_id "
        "JOIN factor_bucket b ON b.id = fe.bucket_id "
        "JOIN instrument ri ON ri.id = b.representative_id "
        "WHERE fe.significant=1 AND w.active=1 AND b.active=1"
    )


def run(socketio=None) -> None:
    if socketio is None:
        try:
            from server.app import socketio as _sio
            socketio = _sio
        except Exception:  # noqa: BLE001
            socketio = None

    with record_run("bucket_alerts") as result:
        s = _settings()
        if not s["enabled"]:
            log.debug("bucket_alerts disabled in settings; skipping")
            result["rows"] = 0
            return

        exposures = _significant_exposures()
        if not exposures:
            result["rows"] = 0
            return

        # Cache per rep so each bucket is z-scored once even when many watches
        # share it.
        z_cache: dict[int, "object | None"] = {}

        def _z_for(rep_iid: int):
            if rep_iid not in z_cache:
                z_cache[rep_iid] = bucket_zscore(rep_iid)
            return z_cache[rep_iid]

        fired = 0
        for e in exposures:
            bz = _z_for(e["representative_id"])
            if bz is None:
                continue
            hit = evaluate_bucket(
                inp=BucketAlertInput(
                    bucket_id=e["bucket_id"], bucket_label=e["bucket_label"],
                    rep_symbol=e["rep_symbol"], beta=e["beta"],
                    bucket_return=bz.today_return, z=bz.z, direction=e["direction"],
                ),
                z_warn=s["z_warn"], z_high=s["z_high"], z_critical=s["z_critical"],
            )
            if hit is None:
                continue
            aid = engine.fire(
                instrument_id=e["watch_iid"], symbol=e["watch_symbol"],
                direction=e["direction"], hit=hit, socketio=socketio,
            )
            if aid is not None:
                fired += 1
        result["rows"] = fired
        log.info("bucket_alerts: %d significant exposures evaluated, %d alerts fired",
                 len(exposures), fired)
