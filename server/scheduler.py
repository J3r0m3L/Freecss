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

from server.alerts.quiet_hours import ET
from server.db import get_setting
from server.jobs import (
    earnings_sync,
    massive_news_poll,
    profile_text_refresh,
    pushover_ack,
    quiet_digest,
    quote_stream,
    threshold_eval,
    tick_aggregator,
    x_account_poll,
)

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
    scheduler.add_job(threshold_eval.run, "interval", seconds=5, id="threshold_evaluator")
    scheduler.add_job(quote_stream.run, "interval", seconds=30, id="quote_stream_supervisor")
    scheduler.add_job(pushover_ack.run, "interval", seconds=30, id="pushover_ack_poll")

    # Phase 2: news/social/earnings.
    scheduler.add_job(massive_news_poll.run, "interval", hours=1,
                      id="massive_news_poll")
    scheduler.add_job(x_account_poll.run, "interval", minutes=1,
                      id="x_account_poll")
    scheduler.add_job(earnings_sync.run, "cron", hour=2, minute=0,
                      id="earnings_sync")
    # Monthly Haiku refresh: 1st-Sun-of-month at 03:30 local. APScheduler can't
    # express "1st Sunday" directly, so we schedule every Sunday at 03:30 and
    # let the job's own ≤7-day skip rule keep it monthly per symbol.
    scheduler.add_job(profile_text_refresh.run, "cron", day_of_week="sun",
                      hour=3, minute=30, id="profile_text_refresh")

    # Morning digest at the configured ET time (default 08:00).
    digest_hhmm = (get_setting("global", {}) or {}).get("quiet_hours", {}).get(
        "digest_time_et", "08:00")
    dh, dm = (int(x) for x in digest_hhmm.split(":"))
    scheduler.add_job(quiet_digest.run, "cron", hour=dh, minute=dm,
                      timezone=ET, id="quiet_digest_send")

    scheduler.start()
    log.info("scheduler started with jobs: %s", [j.id for j in scheduler.get_jobs()])


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
