from automation.scheduler import (
    add_job,
    start_scheduler,
)

from automation.jobs import (
    send_due_reminders,
    # follow_up_leads and generate_daily_sales_summary are still just
    # placeholders (they log a line and do nothing) - left importable in
    # automation/jobs.py for whenever real logic gets built, but not
    # registered on the scheduler so the job list only reflects jobs that
    # actually do something.
)

from automation.runner import run_automation


def initialize_scheduler():

    add_job(
        send_due_reminders,
        hour=9,
        minute=0,
        job_id="daily_reminders"
    )

    # ⭐ Automation Engine
    # add_job() already logs "Registered interval job: automation_runner"
    # (see automation/scheduler.py) - no need to say it again here.
    add_job(
        run_automation,
        interval_minutes=1,
        job_id="automation_runner"
    )
    start_scheduler()