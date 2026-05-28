"""Console notifier — prints alerts to the log. Phase 0 default and the
fallback when Pushover credentials are absent."""
from __future__ import annotations

import logging

log = logging.getLogger("deleveraging_watch.notify")


class ConsoleNotifier:
    name = "console"

    def send(self, *, category, title, body, severity, url=None):
        from server.alerts.notifiers import NotifyResult

        log.warning("[ALERT/%s/%s] %s — %s%s", severity, category, title, body,
                    f"  ({url})" if url else "")
        return NotifyResult(ok=True, detail="logged to console")
