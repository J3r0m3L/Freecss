"""Deterministic smoke test for the Phase 1 alert engine.

Inserts a watch, forges ticks simulating various moves, and asserts the rules
engine + orchestrator behave correctly across adverse/aligned, severity bands,
dedup, and quiet-hours routing. Run with: `python -m scripts.smoke_alerts`.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# Run against a throwaway DB so this never touches the real one.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DW_DB_PATH"] = _tmp.name

from server.app import create_app  # noqa: E402  — env must be set before import
from server.alerts import Severity, engine
from server.alerts.rules import evaluate
from server.db import execute, one, rows


def _insert_watch(symbol: str, direction: str) -> tuple[int, int]:
    cur = execute(
        "INSERT INTO instrument(symbol, display_name, asset_class, data_adapter) "
        "VALUES(?,?,?,?)",
        (symbol, symbol, "equity", "stub"),
    )
    iid = cur.lastrowid
    cur = execute(
        "INSERT INTO watch(instrument_id, direction) VALUES(?,?)",
        (iid, direction),
    )
    return iid, cur.lastrowid


def _seed_ticks(iid: int, *, start_px: float, end_px: float, n: int = 30,
                spread_bps: float = 10.0):
    """Linearly walk from start_px to end_px over the trailing 5 minutes."""
    now = datetime.now(timezone.utc)
    step = (end_px - start_px) / max(n - 1, 1)
    for i in range(n):
        ts = (now - timedelta(seconds=(n - 1 - i) * 10)).isoformat()
        px = start_px + step * i
        half = px * spread_bps / 2 / 10_000
        execute(
            "INSERT INTO tick(instrument_id, ts, bid, ask, last, trade_size) "
            "VALUES(?,?,?,?,?,?)",
            (iid, ts, px - half, px + half, px, 1000),
        )


def _watch(watch_id: int) -> dict:
    return one(
        "SELECT w.id, w.instrument_id, w.direction, w.px_jump_pct, w.px_jump_window_s, "
        "w.spread_bps_max, w.volume_zscore, i.symbol "
        "FROM watch w JOIN instrument i ON i.id=w.instrument_id WHERE w.id=?",
        (watch_id,),
    )


def main() -> int:
    create_app(start_background=False)
    failed = 0

    def check(name: str, cond: bool, detail: str = ""):
        nonlocal failed
        if cond:
            print(f"  ✓ {name}")
        else:
            print(f"  ✗ {name}  {detail}")
            failed += 1

    # --- Test 1: adverse price jump (BULL + 5% drop) → high severity, adverse=True ---
    print("\n[1] adverse BULL drop -5%")
    iid, _ = _insert_watch("ABCD", "BULL")
    _seed_ticks(iid, start_px=100.0, end_px=95.0, spread_bps=10)
    w = _watch(_)
    hits = evaluate(w, settings={})
    px_hits = [h for h in hits if h.kind == "px_jump"]
    check("px_jump hit produced", len(px_hits) == 1)
    if px_hits:
        h = px_hits[0]
        check("severity == high", h.severity == Severity.HIGH, f"got {h.severity}")
        check("adverse == True", h.adverse is True)
        check("pct ≈ -5%", abs(h.payload["pct"] - (-0.05)) < 0.001, f"pct={h.payload['pct']}")

    # --- Test 2: aligned move (BULL + 5% rise) → adverse=False, still produces a hit ---
    print("\n[2] aligned BULL rise +5% — logged, not paged")
    iid2, wid2 = _insert_watch("EFGH", "BULL")
    _seed_ticks(iid2, start_px=100.0, end_px=105.0)
    hits2 = evaluate(_watch(wid2), settings={})
    px2 = [h for h in hits2 if h.kind == "px_jump"]
    check("px_jump hit produced", len(px2) == 1)
    if px2:
        check("adverse == False (aligned)", px2[0].adverse is False)

    # --- Test 3: tiny move (BEAR + 0.5%) → no hit ---
    print("\n[3] tiny move — no hit")
    iid3, wid3 = _insert_watch("IJKL", "BEAR")
    _seed_ticks(iid3, start_px=100.0, end_px=100.5)
    check("no hits below threshold", evaluate(_watch(wid3), settings={}) == [])

    # --- Test 4: critical drop (BULL -8%) → severity critical ---
    print("\n[4] critical BULL drop -8%")
    iid4, wid4 = _insert_watch("MNOP", "BULL")
    _seed_ticks(iid4, start_px=100.0, end_px=92.0)
    hits4 = evaluate(_watch(wid4), settings={})
    px4 = [h for h in hits4 if h.kind == "px_jump"]
    if px4:
        check("severity == critical", px4[0].severity == Severity.CRITICAL,
              f"got {px4[0].severity}")

    # --- Test 5: spread blow-out (BULL drop + 200bps spread) → spread hit too ---
    print("\n[5] adverse drop + wide spread")
    iid5, wid5 = _insert_watch("QRST", "BULL")
    _seed_ticks(iid5, start_px=100.0, end_px=96.0, spread_bps=200)
    hits5 = evaluate(_watch(wid5), settings={})
    kinds = {h.kind for h in hits5}
    check("px_jump in hits", "px_jump" in kinds, f"kinds={kinds}")
    check("spread in hits", "spread" in kinds, f"kinds={kinds}")
    s_hit = next((h for h in hits5 if h.kind == "spread"), None)
    if s_hit:
        check("spread severity = critical (>150bps)", s_hit.severity == Severity.CRITICAL)

    # --- Test 6: engine.fire — adverse high during quiet hours → quiet_queued=1 ---
    print("\n[6] engine.fire — adverse HIGH during quiet hours queues for digest")
    iid6, wid6 = _insert_watch("UVWX", "BULL")
    _seed_ticks(iid6, start_px=100.0, end_px=95.0)
    w6 = _watch(wid6)
    hits6 = evaluate(w6, settings={})
    h6 = next(h for h in hits6 if h.kind == "px_jump")
    aid = engine.fire(instrument_id=iid6, symbol="UVWX",
                      direction="BULL", hit=h6, socketio=None)
    check("alert persisted", aid is not None)
    if aid:
        row = one("SELECT severity, adverse, quiet_queued, notified_via FROM alert WHERE id=?", (aid,))
        check("severity stored", row["severity"] == "high")
        check("adverse stored", row["adverse"] == 1)
        # Quiet-hours behaviour depends on current ET clock; check both branches.
        from server.alerts.quiet_hours import is_quiet
        if is_quiet():
            check("quiet_queued=1 (quiet hours)", row["quiet_queued"] == 1,
                  f"row={dict(row)}")
        else:
            check("paged via console (work hours)", row["notified_via"] == "console:warn",
                  f"row={dict(row)}")

    # --- Test 7: dedup — same-kind same-severity within 15 min suppressed ---
    print("\n[7] dedup — re-fire same kind/severity suppressed")
    dup = engine.fire(instrument_id=iid6, symbol="UVWX",
                      direction="BULL", hit=h6, socketio=None)
    check("second fire deduped (None)", dup is None)

    # --- Test 8: aligned hit logs but does not page ---
    print("\n[8] aligned hit logs but does not page")
    h_aligned = px2[0] if px2 else None
    if h_aligned:
        aid8 = engine.fire(instrument_id=iid2, symbol="EFGH",
                           direction="BULL", hit=h_aligned, socketio=None)
        check("aligned alert persisted", aid8 is not None)
        if aid8:
            r8 = one("SELECT notified_via, adverse FROM alert WHERE id=?", (aid8,))
            check("notified_via == 'log'", r8["notified_via"] == "log")
            check("adverse stored = 0", r8["adverse"] == 0)

    # --- Summary ---
    total_alerts = one("SELECT COUNT(*) c FROM alert")["c"]
    print(f"\nalerts in DB: {total_alerts}")
    print("most recent alerts:")
    for r in rows("SELECT id, kind, severity, adverse, notified_via, quiet_queued, payload_json "
                  "FROM alert ORDER BY id DESC LIMIT 5"):
        print("  ", dict(r) | {"payload_json": json.loads(r["payload_json"])})

    if failed:
        print(f"\nFAIL: {failed} assertion(s) failed")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
