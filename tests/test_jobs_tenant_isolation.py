"""
Regression tests for a real cross-tenant bug in
automation/jobs.py's send_due_reminders(): it used to call
reminder_manager.get_reminders() with no business_phone at all, which
per that function's own docstring returns *every* business's pending
reminders. Since automation/service.py's initialize_scheduler() runs
inside every single customer's own deployment (see main.py), each of
those deployments fired this job independently - meaning every
business's customers received their reminder once per deployment, sent
from whichever business's Twilio number happened to run the job.

Also covers a second bug in the same function: the WhatsApp message body
used reminder.get("title")/reminder.get("notes"), keys that don't exist
on a reminder row (see reminder_manager.get_reminders() - the real key
is "reminder_text") - every reminder ever sent read the same generic
"Follow up" placeholder regardless of what the reminder actually said.

whatsapp.send_message() is monkeypatched to avoid hitting the real
Twilio API, same approach as tests/test_manual_reply.py.
"""

import asyncio

import automation.jobs as jobs
from crm.customer_mapping import save_customer_number, save_mapping
from reminder_manager import create_reminder


def _mock_send(sent):

    async def _send(to, text):
        sent.append((to, text))

    return _send


def _two_businesses_with_reminders():
    save_customer_number("u1", "+10000000001", "bizA")
    save_customer_number("u2", "+10000000002", "bizB")

    save_mapping("+91100000001", "+10000000001", "Alice")
    save_mapping("+91100000002", "+10000000002", "Bob")

    create_reminder("+91100000001", "Follow up with Alice", due_in_days=-1)
    create_reminder("+91100000002", "Follow up with Bob", due_in_days=-1)


def test_send_due_reminders_only_sends_for_this_deployments_business(
    isolated_db, monkeypatch
):

    _two_businesses_with_reminders()

    sent = []
    monkeypatch.setattr(jobs, "send_message", _mock_send(sent))
    monkeypatch.setattr(jobs, "BUSINESS_ID", "bizA")

    asyncio.run(jobs.send_due_reminders())

    recipients = {to for to, _ in sent}
    assert recipients == {"+91100000001"}


def test_send_due_reminders_uses_real_reminder_text(isolated_db, monkeypatch):

    _two_businesses_with_reminders()

    sent = []
    monkeypatch.setattr(jobs, "send_message", _mock_send(sent))
    monkeypatch.setattr(jobs, "BUSINESS_ID", "bizA")

    asyncio.run(jobs.send_due_reminders())

    assert len(sent) == 1
    _, message = sent[0]
    assert "Follow up with Alice" in message


def test_send_due_reminders_skips_when_business_not_active(
    isolated_db, monkeypatch
):

    _two_businesses_with_reminders()

    sent = []
    monkeypatch.setattr(jobs, "send_message", _mock_send(sent))
    # No business registered under this id at all - the deployment's own
    # business isn't in the active registry (e.g. deactivated), so
    # nothing should be sent rather than falling back to unscoped.
    monkeypatch.setattr(jobs, "BUSINESS_ID", "biz_not_registered")

    asyncio.run(jobs.send_due_reminders())

    assert sent == []
