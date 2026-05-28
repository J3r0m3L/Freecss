"""Shared pytest fixtures (DESIGN.md §18).

Per-test isolation: every test starts with a fresh SQLite file at a tempfile
path, with the schema applied and seeds loaded. No test touches the real
`deleveraging_watch.db`.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# CRITICAL: set DW_DB_PATH BEFORE any `server` import, so the config singleton
# (which reads env at construction time) points at the tempfile path.
_TMPDIR = Path(tempfile.mkdtemp(prefix="dw-tests-"))
os.environ["DW_DB_PATH"] = str(_TMPDIR / "test.db")
# Don't shell out to Pushover or any HTTP service from tests.
os.environ.setdefault("DW_NOTIFIER", "console")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Drop and re-init the test DB (incl. seeds) before each test."""
    from server import db as db_mod

    # Close any cached thread-local connection so its file handle releases.
    conn = getattr(db_mod._local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        finally:
            db_mod._local.conn = None

    base = Path(os.environ["DW_DB_PATH"])
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(base) + suffix)
        if p.exists():
            p.unlink()

    db_mod.init_db()
    yield


@pytest.fixture
def app():
    """Flask app with background workers disabled — tests drive jobs directly."""
    from server.app import create_app

    return create_app(start_background=False)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_watch():
    """Insert an instrument + active watch; return (instrument_id, watch_id)."""
    from server.db import execute

    def _mk(symbol: str, direction: str = "BULL") -> tuple[int, int]:
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

    return _mk


@pytest.fixture
def seed_ticks():
    """Write a linear price walk into `tick` ending at "now"."""
    from server.db import execute

    def _seed(iid: int, *, start_px: float = 100.0, end_px: float = 100.0,
              n: int = 30, spread_bps: float = 10.0, span_seconds: int = 290):
        now = datetime.now(timezone.utc)
        step = (end_px - start_px) / max(n - 1, 1)
        dt = span_seconds / max(n - 1, 1)
        for i in range(n):
            ts = (now - timedelta(seconds=(n - 1 - i) * dt)).isoformat()
            px = start_px + step * i
            half = px * spread_bps / 2 / 10_000
            execute(
                "INSERT INTO tick(instrument_id, ts, bid, ask, last, trade_size) "
                "VALUES(?,?,?,?,?,?)",
                (iid, ts, px - half, px + half, px, 1000),
            )

    return _seed


@pytest.fixture
def watch_row():
    """Fetch a watch row in the shape rules.evaluate() expects."""
    from server.db import one

    def _get(watch_id: int) -> dict:
        return one(
            "SELECT w.id, w.instrument_id, w.direction, w.px_jump_pct, "
            "       w.px_jump_window_s, w.spread_bps_max, w.volume_zscore, i.symbol "
            "FROM watch w JOIN instrument i ON i.id=w.instrument_id WHERE w.id=?",
            (watch_id,),
        )

    return _get


@pytest.fixture
def fake_socketio():
    """Records every (event, payload) for engine-broadcast assertions."""
    class _Fake:
        def __init__(self) -> None:
            self.emissions: list[tuple[str, dict]] = []

        def emit(self, event: str, payload: dict) -> None:
            self.emissions.append((event, payload))

    return _Fake()
