"""Config defaults + credential-status presence/absence (DESIGN.md §11.E).

Credentials must never leak as values — only the booleans (present/absent).
"""
from server.config import Config


def test_defaults():
    c = Config()
    assert c.host == "127.0.0.1"
    assert c.port == 5001
    assert c.data_adapter == "stub"
    assert c.notifier == "console"


def test_credential_status_keys():
    status = Config().credential_status()
    expected = {
        "MASSIVE_API_KEY", "FINNHUB_API_KEY", "ANTHROPIC_API_KEY", "X_BEARER_TOKEN",
        "PUSHOVER_USER_KEY", "PUSHOVER_APP_TOKEN_CRITICAL", "PUSHOVER_APP_TOKEN_WARN",
        "PUSHOVER_APP_TOKEN_NEWS", "PUSHOVER_APP_TOKEN_INFO",
    }
    assert set(status.keys()) == expected
    # All values are booleans, not strings — no key material can ever leak through this API.
    assert all(isinstance(v, bool) for v in status.values())


def test_massive_key_falls_back_to_polygon_alias(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.setenv("POLYGON_API_KEY", "legacy")
    assert Config().credential_status()["MASSIVE_API_KEY"] is True


def test_missing_keys_report_false(monkeypatch):
    for k in ("MASSIVE_API_KEY", "POLYGON_API_KEY", "FINNHUB_API_KEY",
              "ANTHROPIC_API_KEY", "X_BEARER_TOKEN", "PUSHOVER_USER_KEY",
              "PUSHOVER_APP_TOKEN_CRITICAL", "PUSHOVER_APP_TOKEN_WARN",
              "PUSHOVER_APP_TOKEN_NEWS", "PUSHOVER_APP_TOKEN_INFO"):
        monkeypatch.delenv(k, raising=False)
    assert not any(Config().credential_status().values())
