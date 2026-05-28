"""Alert engine: dedup, persistence, WS broadcast, adverse-only paging."""
from server.alerts import Severity, engine
from server.alerts.rules import RuleHit
from server.db import one


def _hit(kind="px_jump", severity=Severity.HIGH, adverse=True, **payload):
    return RuleHit(kind=kind, severity=severity, adverse=adverse,
                   payload={"pct": -0.05, "threshold": 0.03, **payload})


def test_fire_persists_and_broadcasts(make_watch, fake_socketio):
    iid, _ = make_watch("AAA", "BULL")
    aid = engine.fire(instrument_id=iid, symbol="AAA",
                      direction="BULL", hit=_hit(), socketio=fake_socketio)
    assert aid is not None
    row = one("SELECT * FROM alert WHERE id=?", (aid,))
    assert row["kind"] == "px_jump"
    assert row["severity"] == "high"
    assert row["adverse"] == 1

    # WS emission shape: one ("alerts", payload) tuple with the right fields.
    assert len(fake_socketio.emissions) == 1
    event, payload = fake_socketio.emissions[0]
    assert event == "alerts"
    assert payload["symbol"] == "AAA"
    assert payload["kind"] == "px_jump"
    assert payload["severity"] == "high"
    assert payload["adverse"] is True


def test_dedup_within_window_suppressed(make_watch, fake_socketio):
    iid, _ = make_watch("BBB", "BULL")
    first = engine.fire(instrument_id=iid, symbol="BBB",
                        direction="BULL", hit=_hit(), socketio=fake_socketio)
    second = engine.fire(instrument_id=iid, symbol="BBB",
                         direction="BULL", hit=_hit(), socketio=fake_socketio)
    assert first is not None
    assert second is None
    # Only one row, only one broadcast.
    assert one("SELECT COUNT(*) c FROM alert WHERE instrument_id=?", (iid,))["c"] == 1
    assert len(fake_socketio.emissions) == 1


def test_dedup_allows_escalation(make_watch, fake_socketio):
    iid, _ = make_watch("CCC", "BULL")
    first = engine.fire(instrument_id=iid, symbol="CCC",
                        direction="BULL",
                        hit=_hit(severity=Severity.WARN), socketio=fake_socketio)
    assert first is not None
    second = engine.fire(instrument_id=iid, symbol="CCC",
                         direction="BULL",
                         hit=_hit(severity=Severity.CRITICAL), socketio=fake_socketio)
    assert second is not None
    assert one("SELECT COUNT(*) c FROM alert WHERE instrument_id=?", (iid,))["c"] == 2


def test_aligned_hit_logged_not_paged(make_watch, fake_socketio):
    iid, _ = make_watch("DDD", "BULL")
    aid = engine.fire(instrument_id=iid, symbol="DDD",
                      direction="BULL",
                      hit=_hit(adverse=False), socketio=fake_socketio)
    row = one("SELECT notified_via, adverse FROM alert WHERE id=?", (aid,))
    assert row["adverse"] == 0
    assert row["notified_via"] == "log"


def test_quiet_hours_queues_high_for_digest(make_watch, fake_socketio, monkeypatch):
    """Force quiet hours regardless of when tests run."""
    from server.alerts import engine as eng_mod

    monkeypatch.setattr(eng_mod.quiet_hours, "route", lambda severity: "queue")
    iid, _ = make_watch("EEE", "BULL")
    aid = engine.fire(instrument_id=iid, symbol="EEE",
                      direction="BULL",
                      hit=_hit(severity=Severity.HIGH), socketio=fake_socketio)
    row = one("SELECT quiet_queued, notified_via FROM alert WHERE id=?", (aid,))
    assert row["quiet_queued"] == 1
    assert row["notified_via"] is None


def test_critical_pages_through_quiet_hours(make_watch, fake_socketio, monkeypatch):
    from server.alerts import engine as eng_mod

    monkeypatch.setattr(eng_mod.quiet_hours, "route",
                        lambda severity: "page" if severity == Severity.CRITICAL else "queue")
    iid, _ = make_watch("FFF", "BULL")
    aid = engine.fire(instrument_id=iid, symbol="FFF",
                      direction="BULL",
                      hit=_hit(severity=Severity.CRITICAL), socketio=fake_socketio)
    row = one("SELECT notified_via FROM alert WHERE id=?", (aid,))
    assert row["notified_via"] == "console:critical"
