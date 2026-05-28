"""Engine handling of the Phase 5 `factor:<bucket>` kind."""
from server.alerts import Severity, engine
from server.alerts.rules import RuleHit
from server.db import one


def _hit(label: str = "Semis", *, adverse: bool = True) -> RuleHit:
    return RuleHit(
        kind=f"factor:{label}",
        severity=Severity.HIGH,
        adverse=adverse,
        payload={
            "bucket_id": 1, "bucket_label": label, "rep_symbol": "SOXX",
            "beta": 1.42, "bucket_return": -0.028, "z": -4.1, "thesis": "BULL",
        },
    )


def test_label_for_kind_strips_factor_prefix():
    label = engine._label_for_kind("factor:Semis")
    assert "Semis" in label and "factor" in label


def test_title_body_renders_factor_payload():
    title, body = engine._title_body("AAPL", "BULL", _hit())
    assert "Semis" in title
    assert "SOXX" in body and "-2.80%" in body and "z=-4.10" in body


def test_dedup_is_per_bucket(make_watch, fake_socketio):
    """Two consecutive fires with different bucket labels both persist (kinds differ)."""
    iid, _ = make_watch("AAPL", "BULL")
    a = engine.fire(instrument_id=iid, symbol="AAPL", direction="BULL",
                    hit=_hit("Semis"), socketio=fake_socketio)
    b = engine.fire(instrument_id=iid, symbol="AAPL", direction="BULL",
                    hit=_hit("AI"), socketio=fake_socketio)
    assert a is not None and b is not None
    assert one("SELECT COUNT(*) c FROM alert WHERE kind LIKE 'factor:%'")["c"] == 2


def test_default_settings_include_bucket_alerts(client):
    body = client.get("/api/settings").json
    assert body["settings"]["bucket_alerts"]["enabled"] is True
    assert body["settings"]["bucket_alerts"]["z_warn"] == 3.0
    assert body["settings"]["bucket_alerts"]["z_critical"] == 5.0
