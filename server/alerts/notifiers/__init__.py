"""Notifier seam (DESIGN.md §12). Pushover is the v1 channel; console is the
Phase 0 default and the no-credentials fallback."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from server.alerts import AlertCategory, Severity
from server.alerts.notifiers.console import ConsoleNotifier
from server.config import config


@dataclass(frozen=True)
class NotifyResult:
    ok: bool
    detail: str = ""
    receipt: str | None = None  # set for priority=2 emergency sends (§12 ack tracking)


class Notifier(Protocol):
    def send(self, *, category: AlertCategory, title: str, body: str,
             severity: Severity, url: str | None = None) -> NotifyResult: ...


def make_notifier(name: str | None = None) -> Notifier:
    name = name or config.notifier
    if name == "console":
        return ConsoleNotifier()
    if name == "pushover":
        from server.alerts.notifiers.pushover import PushoverNotifier

        return PushoverNotifier()
    raise ValueError(f"unknown notifier {name!r} (supported: 'console', 'pushover')")


__all__ = ["Notifier", "NotifyResult", "ConsoleNotifier", "make_notifier"]
