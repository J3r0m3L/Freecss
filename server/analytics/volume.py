"""Volume z-score vs the intraday baseline (DESIGN.md §8 volume rule).

The rule is "5m window volume > Nσ above the 20d intraday-mean for that
minute-of-day." We approximate minute-of-day by the bar's UTC HH:MM (a fixed
offset from ET outside DST shifts) and pull the matching slots from `bar_1m`
over the trailing `lookback_days`. Returns None when there isn't enough history
to be meaningful — so a fresh DB simply doesn't fire volume alerts yet.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from server.db import get_db

_MIN_SAMPLES = 10


@dataclass(frozen=True)
class VolumeZ:
    z: float
    current_per_min: float
    baseline_mean: float
    baseline_std: float
    n_samples: int


def volume_zscore(instrument_id: int, *, window_minutes: int = 5,
                  lookback_days: int = 20) -> VolumeZ | None:
    db = get_db()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    window_start = now - timedelta(minutes=window_minutes)

    recent = db.execute(
        "SELECT ts, v FROM bar_1m WHERE instrument_id=? AND ts >= ? AND ts < ? ",
        (instrument_id, window_start.isoformat(), now.isoformat()),
    ).fetchall()
    if not recent:
        return None
    current_per_min = sum((r["v"] or 0) for r in recent) / len(recent)

    # Minute-of-day slots covered by the current window (UTC HH:MM).
    slots = {
        (window_start + timedelta(minutes=i)).strftime("%H:%M")
        for i in range(window_minutes)
    }
    cutoff = (now - timedelta(days=lookback_days)).isoformat()
    today = now.strftime("%Y-%m-%d")

    samples: list[float] = []
    for row in db.execute(
        "SELECT ts, v FROM bar_1m WHERE instrument_id=? AND ts >= ?",
        (instrument_id, cutoff),
    ).fetchall():
        ts = row["ts"]
        if ts[:10] == today:  # exclude today so we compare against history
            continue
        if ts[11:16] in slots:
            samples.append(row["v"] or 0)

    if len(samples) < _MIN_SAMPLES:
        return None
    mean = statistics.mean(samples)
    std = statistics.pstdev(samples)
    if std <= 0:
        return None
    return VolumeZ(
        z=(current_per_min - mean) / std,
        current_per_min=current_per_min,
        baseline_mean=mean,
        baseline_std=std,
        n_samples=len(samples),
    )
