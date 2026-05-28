"""Alert orchestration (DESIGN.md §8, §12): dedup → persist → broadcast → route.

`fire()` is the single choke point every rule hit flows through. It enforces the
15-minute per-(symbol, kind) dedup (unless severity escalates), writes the
`alert` row, broadcasts on the `alerts` Socket.IO channel, and — only for
adverse hits — routes through quiet hours to the notifier or the morning-digest
queue.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from server.alerts import Severity
from server.alerts import quiet_hours
from server.alerts.notifiers import make_notifier
from server.alerts.notifiers.pushover import category_for
from server.alerts.rules import RuleHit, severity_rank
from server.config import config
from server.db import get_db, one

log = logging.getLogger("deleveraging_watch.alerts")

_DEDUP_WINDOW_S = 15 * 60
_notifier = make_notifier()

_KIND_LABEL = {
    "px_jump": "price jump",
    "spread": "spread blow-out",
    "volume": "volume spike",
    "combined": "Deleveraging",
    "news": "news",
    "social_x": "X post",
    "earnings": "earnings",
}


def _label_for_kind(kind: str) -> str:
    """Resolve kind → human label, honoring the `factor:<bucket>` namespace."""
    if kind.startswith("factor:"):
        return f"factor move — {kind.split(':', 1)[1]}"
    return _KIND_LABEL.get(kind, kind)


def _bull_bear(direction: str) -> str:
    return "🐂" if direction == "BULL" else "🐻"


def _suppressed_by_dedup(instrument_id: int, hit: RuleHit) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=_DEDUP_WINDOW_S)).isoformat()
    last = one(
        "SELECT severity FROM alert WHERE instrument_id=? AND kind=? AND ts >= ? "
        "ORDER BY ts DESC LIMIT 1",
        (instrument_id, hit.kind, cutoff),
    )
    if last is None:
        return False
    # Allow a repeat only if severity escalates.
    return severity_rank(hit.severity) <= severity_rank(Severity(last["severity"]))


def _title_body(symbol: str, direction: str, hit: RuleHit) -> tuple[str, str]:
    bb = _bull_bear(direction)
    label = _label_for_kind(hit.kind)
    p = hit.payload
    title = f"{symbol} — {label} vs {bb} thesis"
    if hit.kind == "px_jump":
        body = f"Δ {p['pct'] * 100:+.2f}% over window (threshold {p['threshold'] * 100:.1f}%)"
    elif hit.kind == "spread":
        body = f"spread {p['spread_bps']} bps sustained (max {p['threshold']:.0f})"
    elif hit.kind == "volume":
        body = f"volume z={p['z']}σ (n={p.get('n_samples')})"
    elif hit.kind == "combined":
        body = f"Δ {p['pct'] * 100:+.2f}% + volume z={p.get('z')}σ — likely forced unwind"
    elif hit.kind in ("news", "social_x"):
        # Title from the headline/tweet itself; body carries sentiment + relevance.
        title = f"{symbol} — {label}: {p.get('title', '')[:180]}"
        body = (f"sent={p.get('sentiment'):+.2f} rel={p.get('relevance'):.2f} "
                f"({p.get('relevance_source')}) vs {bb}")
    elif hit.kind.startswith("factor:"):
        body = (f"rep {p['rep_symbol']} {p['bucket_return'] * 100:+.2f}% "
                f"(z={p['z']:+.2f}σ); β={p['beta']:+.2f} → "
                f"{'adverse' if hit.adverse else 'aligned'} vs {bb}")
    else:
        body = json.dumps(p)
    return title, body


def fire(*, instrument_id: int, symbol: str, direction: str, hit: RuleHit, socketio=None) -> int | None:
    """Process one rule hit. Returns the new alert id, or None if deduped."""
    if _suppressed_by_dedup(instrument_id, hit):
        return None

    ts = datetime.now(timezone.utc).isoformat()
    db = get_db()
    cur = db.execute(
        "INSERT INTO alert(instrument_id, ts, kind, severity, adverse, payload_json, quiet_queued) "
        "VALUES(?,?,?,?,?,?,0)",
        (instrument_id, ts, hit.kind, hit.severity.value, int(hit.adverse),
         json.dumps(hit.payload)),
    )
    alert_id = cur.lastrowid
    db.commit()

    title, body = _title_body(symbol, direction, hit)

    if socketio is not None:
        socketio.emit("alerts", {
            "id": alert_id, "symbol": symbol, "kind": hit.kind,
            "severity": hit.severity.value, "adverse": hit.adverse,
            "ts": ts, "title": title, "body": body, "payload": hit.payload,
        })

    # Only adverse hits page; aligned breaches are logged (above) but not notified (§1).
    if not hit.adverse:
        db.execute("UPDATE alert SET notified_via='log' WHERE id=?", (alert_id,))
        db.commit()
        return alert_id

    decision = quiet_hours.route(hit.severity)
    url = f"http://{config.host}:{config.port}/instrument/{symbol}"

    if decision == "page":
        category = category_for(hit.severity)
        result = _notifier.send(category=category, title=title, body=body,
                                severity=hit.severity, url=url)
        db.execute(
            "UPDATE alert SET notified_via=?, pushover_receipt=? WHERE id=?",
            (f"{_notifier.name}:{category.value}", result.receipt, alert_id),
        )
    elif decision == "queue":
        db.execute("UPDATE alert SET quiet_queued=1 WHERE id=?", (alert_id,))
        log.info("queued %s/%s for digest (quiet hours)", symbol, hit.kind)
    else:  # drop
        db.execute("UPDATE alert SET notified_via='dropped' WHERE id=?", (alert_id,))
    db.commit()
    return alert_id
