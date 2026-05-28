"""Alert severities/categories and the notifier seam (DESIGN.md §8, §12)."""
from __future__ import annotations

from enum import Enum


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    HIGH = "high"
    CRITICAL = "critical"


class AlertCategory(str, Enum):
    """Pushover application buckets — each maps to its own app token/icon (§3.2)."""
    CRITICAL = "critical"
    WARN = "warn"
    NEWS = "news"
    INFO = "info"


# Severity → Pushover priority (§12).
PUSHOVER_PRIORITY = {
    Severity.INFO: -1,
    Severity.WARN: 0,
    Severity.HIGH: 1,
    Severity.CRITICAL: 2,
}
