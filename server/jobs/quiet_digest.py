"""quiet_digest_send (§7.3, §12) — daily 08:00 ET. Bundle everything queued
during quiet hours into one Pushover message sent via the NEWS category (📰),
priority 0, then mark the rows digested. Skips if the queue is empty (unless
send_empty_digest is on)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from server.alerts import AlertCategory, Severity
from server.alerts.notifiers import make_notifier
from server.config import config
from server.db import get_db, get_setting, rows
from server.jobs import record_run

_SEV_ICON = {"critical": "🚨", "high": "🔔", "warn": "⚠️", "info": "📰"}
_SEV_ORDER = ["critical", "high", "warn"]


def _format(queued: list[dict]) -> tuple[str, str]:
    by_sev: dict[str, list[dict]] = {s: [] for s in _SEV_ORDER}
    for a in queued:
        by_sev.setdefault(a["severity"], []).append(a)
    counts = " · ".join(f"{len(by_sev[s])} {s}" for s in _SEV_ORDER if by_sev[s])
    title = f"Overnight digest — {counts or 'all clear'}"

    lines: list[str] = []
    for sev in _SEV_ORDER:
        items = by_sev[sev]
        if not items:
            continue
        lines.append(f"{_SEV_ICON[sev]} {len(items)} {sev}:")
        for a in items[:10]:
            t = a["ts"][11:16]
            p = json.loads(a["payload_json"]) if a["payload_json"] else {}
            detail = p.get("note") or f"{a['kind']}"
            lines.append(f"  • {t} — {a['symbol']} {detail}")
        if len(items) > 10:
            lines.append(f"  • … and {len(items) - 10} more")
    return title, "\n".join(lines)


def run() -> None:
    qh = (get_setting("global", {}) or {}).get("quiet_hours", {})
    send_empty = qh.get("send_empty_digest", False)

    queued = rows(
        "SELECT a.*, i.symbol FROM alert a JOIN instrument i ON i.id=a.instrument_id "
        "WHERE a.quiet_queued=1 AND a.digested_at IS NULL ORDER BY a.ts"
    )
    if not queued and not send_empty:
        return

    with record_run("quiet_digest_send") as result:
        title, body = _format(queued)
        notifier = make_notifier()
        notifier.send(
            category=AlertCategory.NEWS, title=title,
            body=body or "No queued alerts.", severity=Severity.WARN,  # priority 0
            url=f"http://{config.host}:{config.port}/news",
        )
        now = datetime.now(timezone.utc).isoformat()
        db = get_db()
        for a in queued:
            db.execute(
                "UPDATE alert SET digested_at=?, notified_via='digest' WHERE id=?",
                (now, a["id"]),
            )
        db.commit()
        result["rows"] = len(queued)
