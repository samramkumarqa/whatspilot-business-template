import logging

from reminder_manager import upsert_reminder

logger = logging.getLogger(__name__)


def execute(customer, params, rule=None):
    """
    Create a reminder for a matched customer.
    """

    customer_phone = customer["phone"]

    reminder_text = params.get(
        "text",
        "Follow up customer"
    )

    days = int(
        params.get(
            "days",
            1
        )
    )

    upsert_reminder(
        customer_phone,
        reminder_text,
        days,
        source_rule_id=rule.get("id") if rule else None,
        source_rule_name=rule.get("name") if rule else None
    )

    logger.debug("Reminder created for %s", customer_phone)