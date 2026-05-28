"""Pushover notifier (DESIGN.md §3.2, §12).

Four Pushover applications (critical/warn/news/info) under one account give
distinct lock-screen icons; each has its own app token, all sharing one User
Key. Severity maps to Pushover priority; `critical` uses emergency priority=2
(retry=60, expire=1800) and returns a receipt for ack tracking.

Falls back to the console notifier for any category whose token is missing, so a
partially-configured account still surfaces alerts instead of silently dropping.
"""
from __future__ import annotations

import logging
import os

import requests

from server.alerts import PUSHOVER_PRIORITY, AlertCategory, Severity
from server.alerts.notifiers.console import ConsoleNotifier

log = logging.getLogger("deleveraging_watch.notify")

_API = "https://api.pushover.net/1/messages.json"

_CATEGORY_TOKEN_ENV = {
    AlertCategory.CRITICAL: "PUSHOVER_APP_TOKEN_CRITICAL",
    AlertCategory.WARN: "PUSHOVER_APP_TOKEN_WARN",
    AlertCategory.NEWS: "PUSHOVER_APP_TOKEN_NEWS",
    AlertCategory.INFO: "PUSHOVER_APP_TOKEN_INFO",
}


class PushoverNotifier:
    name = "pushover"

    def __init__(self) -> None:
        self._user = os.environ.get("PUSHOVER_USER_KEY", "")
        self._tokens = {
            cat: os.environ.get(env, "") for cat, env in _CATEGORY_TOKEN_ENV.items()
        }
        self._console = ConsoleNotifier()

    def send(self, *, category: AlertCategory, title: str, body: str,
             severity: Severity, url: str | None = None):
        from server.alerts.notifiers import NotifyResult

        token = self._tokens.get(category)
        if not self._user or not token:
            log.warning("pushover token/user missing for category %s; using console", category)
            return self._console.send(category=category, title=title, body=body,
                                      severity=severity, url=url)

        priority = PUSHOVER_PRIORITY[severity]
        payload = {
            "token": token,
            "user": self._user,
            "title": title[:250],
            "message": body[:1024],
            "priority": priority,
        }
        if url:
            payload["url"] = url
            payload["url_title"] = "Open dashboard"
        if priority == 2:  # emergency — must specify retry/expire (§12)
            payload["retry"] = 60
            payload["expire"] = 1800

        try:
            resp = requests.post(_API, data=payload, timeout=10)
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            log.exception("pushover send failed")
            return NotifyResult(ok=False, detail=str(exc))

        if data.get("status") != 1:
            return NotifyResult(ok=False, detail=str(data.get("errors", data)))
        return NotifyResult(ok=True, detail="sent",
                            receipt=data.get("receipt") if priority == 2 else None)


def category_for(severity: Severity) -> AlertCategory:
    """Map a severity to its Pushover application/icon bucket (§3.2)."""
    if severity == Severity.CRITICAL:
        return AlertCategory.CRITICAL
    if severity in (Severity.HIGH, Severity.WARN):
        return AlertCategory.WARN
    return AlertCategory.INFO
