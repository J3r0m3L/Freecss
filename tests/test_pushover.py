"""Pushover notifier (DESIGN.md §3.2, §12) — mapping + mocked HTTP."""
import pytest

from server.alerts import AlertCategory, Severity
from server.alerts.notifiers.console import ConsoleNotifier
from server.alerts.notifiers.pushover import PushoverNotifier, category_for


def test_category_for_each_severity():
    assert category_for(Severity.CRITICAL) == AlertCategory.CRITICAL
    assert category_for(Severity.HIGH) == AlertCategory.WARN
    assert category_for(Severity.WARN) == AlertCategory.WARN
    assert category_for(Severity.INFO) == AlertCategory.INFO


def test_falls_back_to_console_when_token_missing(monkeypatch):
    for k in ("PUSHOVER_USER_KEY", "PUSHOVER_APP_TOKEN_CRITICAL",
              "PUSHOVER_APP_TOKEN_WARN", "PUSHOVER_APP_TOKEN_NEWS",
              "PUSHOVER_APP_TOKEN_INFO"):
        monkeypatch.delenv(k, raising=False)
    n = PushoverNotifier()
    result = n.send(category=AlertCategory.WARN, title="t", body="b",
                    severity=Severity.WARN, url=None)
    assert result.ok is True
    assert "console" in result.detail.lower()


def test_emergency_send_includes_retry_expire(monkeypatch):
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_APP_TOKEN_CRITICAL", "tk")
    captured: dict = {}

    class _Resp:
        def json(self):
            return {"status": 1, "receipt": "rcpt-123"}

    def _post(url, data=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        return _Resp()

    monkeypatch.setattr("server.alerts.notifiers.pushover.requests.post", _post)
    n = PushoverNotifier()
    result = n.send(category=AlertCategory.CRITICAL, title="X",
                    body="Y", severity=Severity.CRITICAL,
                    url="http://localhost/instrument/X")
    assert result.ok is True
    assert result.receipt == "rcpt-123"
    assert captured["data"]["priority"] == 2
    assert captured["data"]["retry"] == 60
    assert captured["data"]["expire"] == 1800
    assert captured["data"]["url"] == "http://localhost/instrument/X"


def test_warn_send_has_priority_zero(monkeypatch):
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_APP_TOKEN_WARN", "tk")
    captured: dict = {}

    class _Resp:
        def json(self):
            return {"status": 1}

    def _post(url, data=None, timeout=None):
        captured.update(data)
        return _Resp()

    monkeypatch.setattr("server.alerts.notifiers.pushover.requests.post", _post)
    n = PushoverNotifier()
    n.send(category=AlertCategory.WARN, title="t", body="b",
           severity=Severity.WARN)
    assert captured["priority"] == 0
    assert "retry" not in captured  # only emergency sends carry retry/expire


def test_failed_send_returns_not_ok(monkeypatch):
    monkeypatch.setenv("PUSHOVER_USER_KEY", "u")
    monkeypatch.setenv("PUSHOVER_APP_TOKEN_WARN", "tk")

    class _Resp:
        def json(self):
            return {"status": 0, "errors": ["invalid token"]}

    monkeypatch.setattr("server.alerts.notifiers.pushover.requests.post",
                        lambda *a, **kw: _Resp())
    n = PushoverNotifier()
    result = n.send(category=AlertCategory.WARN, title="t", body="b",
                    severity=Severity.WARN)
    assert result.ok is False
    assert "invalid token" in result.detail


def test_console_send_is_noop_safe():
    """The console fallback never fails — it's the universal escape hatch."""
    result = ConsoleNotifier().send(
        category=AlertCategory.INFO, title="t", body="b",
        severity=Severity.INFO,
    )
    assert result.ok is True


# Sanity: every Severity has a known Pushover priority.
@pytest.mark.parametrize("sev,priority", [
    (Severity.INFO, -1), (Severity.WARN, 0), (Severity.HIGH, 1), (Severity.CRITICAL, 2),
])
def test_severity_priority_map(sev, priority):
    from server.alerts import PUSHOVER_PRIORITY
    assert PUSHOVER_PRIORITY[sev] == priority
