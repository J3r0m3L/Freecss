"""Quiet-hours routing (DESIGN.md §3.5, §12). Time-injected to avoid wall-clock flake."""
from datetime import datetime

from server.alerts import Severity
from server.alerts.quiet_hours import ET, is_quiet, route


def _at(*, year=2026, month=5, day=27, hour=10, minute=0):
    # 2026-05-27 is a Wednesday — used as the canonical weekday.
    return datetime(year, month, day, hour, minute, tzinfo=ET)


def test_weekday_in_work_hours_not_quiet():
    assert is_quiet(_at(hour=10)) is False
    assert route(Severity.WARN, now_et=_at(hour=10)) == "page"
    assert route(Severity.CRITICAL, now_et=_at(hour=10)) == "page"
    assert route(Severity.INFO, now_et=_at(hour=10)) == "page"


def test_weekday_after_hours_quiet():
    assert is_quiet(_at(hour=22)) is True
    assert route(Severity.CRITICAL, now_et=_at(hour=22)) == "page"
    assert route(Severity.HIGH, now_et=_at(hour=22)) == "queue"
    assert route(Severity.WARN, now_et=_at(hour=22)) == "queue"
    assert route(Severity.INFO, now_et=_at(hour=22)) == "drop"


def test_weekend_quiet_all_day():
    # 2026-05-30 is a Saturday.
    sat = datetime(2026, 5, 30, 14, 0, tzinfo=ET)
    assert is_quiet(sat) is True
    assert route(Severity.CRITICAL, now_et=sat) == "page"
    assert route(Severity.HIGH, now_et=sat) == "queue"


def test_work_window_boundaries_inclusive_exclusive():
    # 09:00 ET is the open (work starts), 17:00 ET is the close (quiet starts).
    assert is_quiet(_at(hour=9, minute=0)) is False    # open is inclusive
    assert is_quiet(_at(hour=16, minute=59)) is False  # last minute of session
    assert is_quiet(_at(hour=17, minute=0)) is True    # close is exclusive
