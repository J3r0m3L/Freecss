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
    # Phase 1: 'pushover' → PushoverNotifier (4 app tokens, §3.2/§12).
    raise ValueError(f"unknown notifier {name!r} (Phase 0 supports 'console' only)")


__all__ = ["Notifier", "NotifyResult", "ConsoleNotifier", "make_notifier"]
