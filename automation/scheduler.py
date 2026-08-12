from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import logging

logger = logging.getLogger(__name__)


scheduler = AsyncIOScheduler()


def add_job(
    func,
    *,
    hour=None,
    minute=0,
    interval_minutes=None,
    job_id=None
):
    """
    Register a scheduled job.
    """

    if interval_minutes:

        scheduler.add_job(
            func,
            "interval",
            minutes=interval_minutes,
            id=job_id,
            replace_existing=True
        )

        logger.info(
            f"Registered interval job: {job_id}"
        )

        return

    scheduler.add_job(
        func,
        CronTrigger(
            hour=hour,
            minute=minute
        ),
        id=job_id,
        replace_existing=True
    )

    logger.info(
        f"Registered cron job: {job_id}"
    )


def start_scheduler():

    if scheduler.running:

        return

    scheduler.start()

    logger.info("Jobs currently registered:")

    for job in scheduler.get_jobs():
        logger.info("  %s (next run: %s)", job.id, job.next_run_time)

    logger.info(
        "Automation Scheduler Started"
    )


def stop_scheduler():

    if scheduler.running:

        scheduler.shutdown()

        logger.info(
            "Automation Scheduler Stopped"
        )