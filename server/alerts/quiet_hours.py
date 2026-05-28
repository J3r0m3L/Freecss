"""Quiet-hours routing (DESIGN.md §3.5, §12).

Work hours (Mon–Fri 09:00–17:00 ET by default): everything pages. Outside that
and on weekends: only `critical` pages; `high`/`warn` queue to the 08:00 ET
digest; `info` drops entirely.
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from server.alerts import Severity
from server.db import get_setting

ET = ZoneInfo("America/New_York")

_DEFAULTS = {
    "enabled": True,
    "work_start_et": "09:00",
    "work_end_et": "17:00",
    "weekends_quiet": True,
    "digest_time_et": "08:00",
    "send_empty_digest": False,
}

Decision = str  # 'page' | 'queue' | 'drop'


def _settings() -> dict:
    stored = (get_setting("global", {}) or {}).get("quiet_hours", {})
    return {**_DEFAULTS, **stored}


def _parse(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def is_quiet(now_et: datetime | None = None) -> bool:
    s = _settings()
    if not s["enabled"]:
        return False
    now_et = now_et or datetime.now(ET)
    is_weekend = now_et.weekday() >= 5  # Sat=5, Sun=6
    if is_weekend and s["weekends_quiet"]:
        return True
    if is_weekend:  # weekends not forced quiet → treat like a weekday window
        pass
    in_work = _parse(s["work_start_et"]) <= now_et.time() < _parse(s["work_end_et"])
    return not (in_work and not is_weekend)


def route(severity: Severity, *, now_et: datetime | None = None) -> Decision:
    """Where should an adverse alert of this severity go right now?"""
    if not is_quiet(now_et):
        return "page"
    # Quiet hours.
    if severity == Severity.CRITICAL:
        return "page"
    if severity in (Severity.HIGH, Severity.WARN):
        return "queue"
    return "drop"  # info
