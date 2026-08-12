import asyncio
import logging

from reminder_manager import get_reminders
from whatsapp import send_message

logger = logging.getLogger(__name__)


async def send_due_reminders():
    """
    Send WhatsApp reminders that are due.
    """

    logger.info("Running scheduled reminder job")

    # get_reminders() is synchronous sqlite3 code; this job runs on
    # APScheduler's asyncio event loop, so calling it directly would block
    # every other scheduled job (and the whole loop) for its duration.
    reminders = await asyncio.to_thread(get_reminders)

    if not reminders:
        logger.info("No reminders found")
        return

    for reminder in reminders:

        try:

            if reminder.get("status") != "Pending":
                continue

            customer_phone = reminder.get("customer_phone")

            message = (
                f"🔔 Reminder\n\n"
                f"{reminder.get('title', 'Follow up')}\n\n"
                f"{reminder.get('notes', '')}"
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