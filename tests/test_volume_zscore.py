"""Volume z-score baseline (DESIGN.md §8 volume rule)."""
from datetime import datetime, timedelta, timezone

from server.analytics.volume import volume_zscore
from server.db import execute


def _insert_bar(iid: int, ts: datetime, vol: int) -> None:
    execute(
        "INSERT INTO bar_1m(instrument_id, ts, o, h, l, c, v) VALUES(?,?,?,?,?,?,?)",
        (iid, ts.isoformat(), 100, 100, 100, 100, vol),
    )


def test_insufficient_history_returns_none(make_watch):
    iid, _ = make_watch("AAA")
    # Only the current-window bars, no historical baseline → not enough samples.
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    for i in range(5):
        _insert_bar(iid, now - timedelta(minutes=i + 1), 10_000)
    assert volume_zscore(iid) is None


def test_zero_std_returns_none(make_watch):
    """All historical samples identical → std=0; can't compute a z-score."""
    iid, _ = make_watch("BBB")
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    for i in range(5):
        _insert_bar(iid, now - timedelta(minutes=i + 1), 10_000)
    # 15 days × 5 matching slots = 75 historical bars, all the same volume.
    for day in range(1, 16):
        for i in range(5):
            ts = now - timedelta(days=day, minutes=i + 1)
            _insert_bar(iid, ts, 1_000)
    assert volume_zscore(iid) is None


def test_z_score_positive_on_volume_spike(make_watch):
    iid, _ = make_watch("CCC")
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    # Current 5-min window: heavy volume.
    for i in range(5):
        _insert_bar(iid, now - timedelta(minutes=i + 1), 10_000)
    # Historical baseline with some variance so std > 0.
    pattern = [900, 950, 1000, 1050, 1100]
    for day in range(1, 16):
        for i in range(5):
            ts = now - timedelta(days=day, minutes=i + 1)
            _insert_bar(iid, ts, pattern[i])
    result = volume_zscore(iid)
    assert result is not None
    assert result.z > 10        # 10000 vs mean ~1000 / tiny std → very large z
    assert result.n_samples == 75


def test_history_excludes_today(make_watch):
    """Today's bars must not be in the baseline — otherwise the z collapses to ~0."""
    iid, _ = make_watch("DDD")
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    # Current window — high.
    for i in range(5):
        _insert_bar(iid, now - timedelta(minutes=i + 1), 10_000)
    # Pollute "today" earlier with high values that MUST be ignored.
    for i in range(5):
        ts = (now - timedelta(minutes=i + 60))
        if ts.date() == now.date():
            _insert_bar(iid, ts, 10_000)
    # Historical (past days) — small variance, low.
    pattern = [900, 950, 1000, 1050, 1100]
    for day in range(1, 16):
        for i in range(5):
            ts = now - timedelta(days=day, minutes=i + 1)
            _insert_bar(iid, ts, pattern[i])
    result = volume_zscore(iid)
    assert result is not None
    assert result.baseline_mean < 1500  # would be >2000 if today were leaking in
