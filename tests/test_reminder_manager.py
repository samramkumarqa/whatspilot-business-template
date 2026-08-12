"""
Tests for reminder_manager.py's "Mark Done" flow.

Regression context: get_reminders() (backing the Follow-ups page and the
dashboard bell badge's overdue count) used to return every reminder ever
created, with no way to mark one done - complete_reminder() existed but
was never called from anywhere, and even it took a customer_phone rather
than a reminder id, so calling it would have completed every reminder for
that customer at once instead of just the one the user resolved. These
tests cover the fix: completing one reminder by id removes only that one
from get_reminders(), leaving any other reminder for the same customer
untouched.
"""

from reminder_manager import (
    create_reminder,
    get_reminders,
    complete_reminder,
)


def _reminder_id_for(reminders, reminder_text):
    matches = [
        r["id"] for r in reminders
        if r["reminder_text"] == reminder_text
    ]
    assert matches, f"no reminder with text {reminder_text!r} found"
    return matches[0]


def test_get_reminders_lists_newly_created_reminder(isolated_db):

    create_reminder("+19998887777", "Send proposal", due_in_days=-5)

    reminders = get_reminders()

    assert any(
        r["customer_phone"] == "+19998887777"
        and r["reminder_text"] == "Send proposal"
        for r in reminders
    )


def test_complete_reminder_removes_it_from_get_reminders(isolated_db):

    create_reminder("+19998887777", "Send proposal", due_in_days=-5)

    reminder_id = _reminder_id_for(get_reminders(), "Send proposal")

    complete_reminder(reminder_id)

    reminders = get_reminders()

    assert not any(r["id"] == reminder_id for r in reminders)


def test_complete_reminder_only_completes_that_one_reminder(isolated_db):

    # Same customer, two independent reminders (e.g. from two different
    # automation rules) - completing one must not silently complete both,
    # which is exactly what the old customer_phone-keyed complete_reminder()
    # would have done.
    create_reminder("+19998887777", "Send proposal", due_in_days=-5)
    create_reminder("+19998887777", "Check in again", due_in_days=3)

    before = get_reminders()
    proposal_id = _reminder_id_for(before, "Send proposal")

    complete_reminder(proposal_id)

    after = get_reminders()

    assert not any(r["id"] == proposal_id for r in after)
    assert any(
        r["reminder_text"] == "Check in again"
        for r in after
    )


def test_completing_an_already_completed_reminder_is_a_no_op(isolated_db):

    create_reminder("+19998887777", "Send proposal", due_in_days=-5)
    reminder_id = _reminder_id_for(get_reminders(), "Send proposal")

    complete_reminder(reminder_id)
    complete_reminder(reminder_id)  # should not raise, should stay gone

    assert not any(r["id"] == reminder_id for r in get_reminders())
