import asyncio
import logging

from config import BUSINESS_ID
from crm.customer_mapping import get_active_businesses
from reminder_manager import get_reminders
from whatsapp import send_message

logger = logging.getLogger(__name__)


async def send_due_reminders():
    """
    Send WhatsApp reminders that are due, for this deployment's own
    business only.

    BUG FIX: this used to call get_reminders() with no business_phone at
    all, which per that function's own docstring returns every pending
    reminder for every business in the shared Postgres database - and
    since automation/service.py's initialize_scheduler() runs inside
    every single customer's own deployment (see main.py), each of those
    N deployments fired this job independently, meaning every business's
    customers received their reminder N times, sent from N different
    businesses' WhatsApp numbers. See automation/runner.py's
    run_automation() for the same BUSINESS_ID-scoping pattern this now
    mirrors.
    """

    logger.info("Running scheduled reminder job")

    # get_active_businesses() is synchronous Postgres code; this job runs
    # on APScheduler's asyncio event loop, so calling it directly would
    # block every other scheduled job (and the whole loop) for its
    # duration.
    businesses = await asyncio.to_thread(get_active_businesses)

    business = next(
        (b for b in businesses if b["business_id"] == BUSINESS_ID), None
    )

    if business is None:
        logger.info(
            "This deployment's business (%s) is not active - skipping.",
            BUSINESS_ID
        )
        return

    business_phone = business["whatsapp_number"]

    reminders = await asyncio.to_thread(get_reminders, business_phone)

    if not reminders:
        logger.info("No reminders found")
        return

    for reminder in reminders:

        try:

            if reminder.get("status") != "Pending":
                continue

            customer_phone = reminder.get("customer_phone")

            # BUG FIX: get_reminders() rows never had "title"/"notes"
            # keys (they have "reminder_text" - see reminder_manager.py)
            # so this always fell through to the hardcoded defaults
            # below, meaning every reminder WhatsApp message ever sent by
            # this job read the same generic "Follow up" text regardless
            # of what the reminder actually said.
            message = (
                f"🔔 Reminder\n\n"
                f"{reminder.get('reminder_text', 'Follow up')}"
            )

            await send_message(
                customer_phone,
                message
            )

            logger.info(
                f"Reminder sent to {customer_phone}"
            )

        except Exception:

            logger.exception(
                "Reminder sending failed"
            )


async def follow_up_leads():
    """
    Placeholder for future AI follow-up automation.
    """

    logger.info(
        "Running lead follow-up job"
    )


async def generate_daily_sales_summary():
    """
    Placeholder for manager daily summary.
    """

    logger.info(
        "Generating daily sales summary"
    )