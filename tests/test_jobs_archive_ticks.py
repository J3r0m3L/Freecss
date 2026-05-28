"""archive_ticks (DESIGN.md §6 Notes, §7.3)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from server.db import execute, one, rows
from server.jobs import archive_ticks


def _seed_tick(iid: int, *, days_ago: float, last: float = 100.0):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    # Tweak the seconds a bit so PK is unique across calls within a test.
    execute("INSERT INTO tick(instrument_id, ts, bid, ask, last) VALUES(?,?,?,?,?)",
            (iid, ts, last - 0.05, last + 0.05, last))


def test_keeps_hot_window(make_watch, tmp_path, monkeypatch):
    monkeypatch.setattr(archive_ticks, "_ARCHIVE_DIR", tmp_path)
    iid, _ = make_watch("X")
    _seed_tick(iid, days_ago=1)
    _seed_tick(iid, days_ago=10)
    archive_ticks.run()
    assert one("SELECT COUNT(*) c FROM tick")["c"] == 2


def test_archives_cold_ticks_and_deletes(make_watch, tmp_path, monkeypatch):
    monkeypatch.setattr(archive_ticks, "_ARCHIVE_DIR", tmp_path)
    iid, _ = make_watch("X")
    _seed_tick(iid, days_ago=1)
    _seed_tick(iid, days_ago=45)
    _seed_tick(iid, days_ago=400)   # last-year cold tick

    archive_ticks.run()

    # Only the hot tick survives in the DB.
    assert one("SELECT COUNT(*) c FROM tick")["c"] == 1

    # Archive files exist — one per year of cold data.
    archived = list(tmp_path.iterdir())
    assert any(p.suffix in (".parquet", ".gz") for p in archived)


def test_archive_append_is_idempotent(make_watch, tmp_path, monkeypatch):
    """Running twice on the same cold tick doesn't blow up — the second run
    finds nothing to archive (it's already deleted) and is a no-op."""
    monkeypatch.setattr(archive_ticks, "_ARCHIVE_DIR", tmp_path)
    iid, _ = make_watch("X")
    _seed_tick(iid, days_ago=60)

    archive_ticks.run()
    archive_ticks.run()   # should not error

    rec = rows("SELECT rows_written, status FROM job_run "
               "WHERE job_name='archive_ticks' ORDER BY started_at")
    assert [r["status"] for r in rec] == ["ok", "ok"]
    assert rec[-1]["rows_written"] == 0


def test_custom_hot_window(make_watch, tmp_path, monkeypatch):
    monkeypatch.setattr(archive_ticks, "_ARCHIVE_DIR", tmp_path)
    iid, _ = make_watch("X")
    _seed_tick(iid, days_ago=3)
    _seed_tick(iid, days_ago=8)
    # 5-day window: anything older than 5 days should archive.
    archive_ticks.run(hot_window_days=5)
    assert one("SELECT COUNT(*) c FROM tick")["c"] == 1
