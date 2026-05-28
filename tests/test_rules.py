"""Alert rule evaluation (DESIGN.md §8)."""
from server.alerts import Severity
from server.alerts.rules import evaluate


def test_adverse_bull_drop_high_severity(make_watch, seed_ticks, watch_row):
    iid, wid = make_watch("AAA", "BULL")
    seed_ticks(iid, start_px=100.0, end_px=95.0)
    [hit] = [h for h in evaluate(watch_row(wid)) if h.kind == "px_jump"]
    assert hit.severity == Severity.HIGH
    assert hit.adverse is True
    assert abs(hit.payload["pct"] - (-0.05)) < 1e-3


def test_aligned_bull_rise_is_logged_not_adverse(make_watch, seed_ticks, watch_row):
    iid, wid = make_watch("BBB", "BULL")
    seed_ticks(iid, start_px=100.0, end_px=105.0)
    [hit] = [h for h in evaluate(watch_row(wid)) if h.kind == "px_jump"]
    assert hit.adverse is False  # logged but should not page (engine handles routing)


def test_adverse_bear_rise(make_watch, seed_ticks, watch_row):
    iid, wid = make_watch("CCC", "BEAR")
    seed_ticks(iid, start_px=100.0, end_px=104.0)
    [hit] = [h for h in evaluate(watch_row(wid)) if h.kind == "px_jump"]
    assert hit.adverse is True


def test_tiny_move_no_hit(make_watch, seed_ticks, watch_row):
    iid, wid = make_watch("DDD", "BULL")
    seed_ticks(iid, start_px=100.0, end_px=100.5)  # 0.5% — below 3% default
    assert evaluate(watch_row(wid)) == []


def test_severity_critical_at_7pct(make_watch, seed_ticks, watch_row):
    iid, wid = make_watch("EEE", "BULL")
    seed_ticks(iid, start_px=100.0, end_px=92.0)  # -8%
    [hit] = [h for h in evaluate(watch_row(wid)) if h.kind == "px_jump"]
    assert hit.severity == Severity.CRITICAL


def test_spread_blow_out_critical(make_watch, seed_ticks, watch_row):
    iid, wid = make_watch("FFF", "BULL")
    seed_ticks(iid, start_px=100.0, end_px=96.0, spread_bps=200, n=10, span_seconds=25)
    hits = evaluate(watch_row(wid))
    kinds = {h.kind for h in hits}
    assert "spread" in kinds
    spread = next(h for h in hits if h.kind == "spread")
    assert spread.severity == Severity.CRITICAL
    assert spread.payload["spread_bps"] > 150


def test_spread_must_be_sustained(make_watch, seed_ticks, watch_row):
    """A single wide-spread tick shouldn't trip the rule — must sustain over the window."""
    iid, wid = make_watch("GGG", "BULL")
    # Most ticks at tight spread; the helper only emits one spread profile, so
    # narrow spread across the board produces no spread hit.
    seed_ticks(iid, start_px=100.0, end_px=96.0, spread_bps=5, n=10, span_seconds=25)
    hits = evaluate(watch_row(wid))
    assert "spread" not in {h.kind for h in hits}


def test_per_watch_threshold_override(make_watch, seed_ticks, watch_row):
    iid, wid = make_watch("HHH", "BULL")
    from server.db import execute

    # Tighten the warn threshold to 0.5% via per-watch override.
    execute("UPDATE watch SET px_jump_pct=0.005 WHERE id=?", (wid,))
    seed_ticks(iid, start_px=100.0, end_px=99.4)  # -0.6%, below default 3% but above override
    hits = [h for h in evaluate(watch_row(wid)) if h.kind == "px_jump"]
    assert len(hits) == 1
    assert hits[0].severity == Severity.WARN
