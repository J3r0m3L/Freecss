"""Global settings + credential presence (DESIGN.md §7.1, §11.E).

Credentials are never returned as values — only present/absent booleans sourced
from .env. Mutable global defaults (thresholds, quiet hours) live in `setting`.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from server.config import config
from server.db import get_setting, set_setting

bp = Blueprint("settings", __name__, url_prefix="/api")

# Global default thresholds (§8) + quiet hours (§3.5/§12). Per-watch overrides
# (watch.* columns) take precedence; these are the fallback.
_DEFAULTS = {
    "thresholds": {
        "px_jump_pct": 0.03,
        "px_jump_window_s": 300,
        "spread_bps_max": 50.0,
        "volume_zscore": 3.0,
    },
    "quiet_hours": {
        "enabled": True,
        "work_start_et": "09:00",
        "work_end_et": "17:00",
        "weekends_quiet": True,
        "digest_time_et": "08:00",
        "send_empty_digest": False,
    },
    "news_rail": {"enabled": True, "min_relevance": 0.5},
    "exit_liquidity": {"participation": 0.10},
    # Phase 5: bucket-level deleveraging alerts. ON by default per user choice
    # (DESIGN.md §9 originally held these off-by-default "until baseline noise
    # is observed"; gating lives here so a single toggle reverts that policy).
    "bucket_alerts": {
        "enabled": True,
        "z_warn": 3.0,
        "z_high": 4.0,
        "z_critical": 5.0,
    },
}


@bp.get("/settings")
def get_settings():
    stored = get_setting("global", {})
    merged = {**_DEFAULTS, **stored}
    return jsonify({
        "settings": merged,
        "credentials": config.credential_status(),
        "data_adapter": config.data_adapter,
        "notifier": config.notifier,
    })


@bp.patch("/settings")
def patch_settings():
    body = request.get_json(silent=True) or {}
    stored = get_setting("global", {})
    stored.update(body)
    set_setting("global", stored)
    return jsonify({"ok": True, "settings": {**_DEFAULTS, **stored}})
