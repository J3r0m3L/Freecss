"""APScheduler wiring (DESIGN.md §4, §7.3). Single in-process BackgroundScheduler
with a bounded thread pool so a slow job can't starve request handling.

Phase 0 registers only `tick_aggregator`. Later phases add quote-stream
supervision, news/X polling, factor refresh, earnings sync, quiet-hours digest,
liquidity refresh, and tick archival on the same scheduler.
"""
from __future__ import annotations

import logging

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

from server.jobs import tick_aggregator

log = logging.getLogger("deleveraging_watch.scheduler")

scheduler = BackgroundScheduler(
    executors={"default": ThreadPoolExecutor(max_workers=4)},
    job_defaults={"coalesce": True, "max_instances": 1},
    timezone="UTC",
)


def start() -> None:
    if scheduler.running:
        return
    scheduler.add_job(tick_aggregator.run, "interval", seconds=60, id="tick_aggregator")
    scheduler.start()
    log.info("scheduler started with jobs: %s", [j.id for j in scheduler.get_jobs()])


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
