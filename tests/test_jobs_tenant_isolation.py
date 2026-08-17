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

get_reminders() is now scoped by business_id = config.BUSINESS_ID (read
dynamically - see reminder_manager.py), not the business_phone this
module's docstring originally described - see
migrations/add_business_id_to_crm_tables.py's module docstring for why.
That means every reminder created below has to be created while
config.BUSINESS_ID actually points at the right business, same as
create_reminder() would naturally see in a real deployment (BUSINESS_ID
is fixed per deployment, never wrong). automation/jobs.py itself still
reads its own BUSINESS_ID via `from config import BUSINESS_ID` (a static,
module-local copy - see jobs.py) for its "is this deployment's business
active" check, so config.BUSINESS_ID and jobs.BUSINESS_ID both need to be
kept in sync here, not just jobs.BUSINESS_ID.

whatsapp.send_message() is monkeypatched to avoid hitting the real
Twilio API, same approach as tests/test_manual_reply.py.
"""

import asyncio

import config
import automation.jobs as jobs
from crm.customer_mapping import save_customer_number, save_mapping
from reminder_manager import create_reminder


def _mock_send(sent):

    async def _send(to, text):
        sent.append((to, text))

    return _send


def _two_businesses_with_reminders(monkeypatch):
    save_customer_number("u1", "+10000000001", "bizA")
    save_customer_number("u2", "+10000000002", "bizB")

    save_mapping("+91100000001", "+10000000001", "Alice")
    save_mapping("+91100000002", "+10000000002", "Bob")

    # create_reminder() stamps whichever business_id config.BUSINESS_ID
    # currently points at (see reminder_manager.py) - each business's own
    # reminder has to be created while BUSINESS_ID is set to that
    # business's own id.
    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    create_reminder("+91100000001", "Follow up with Alice", due_in_days=-1)

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    create_reminder("+91100000002", "Follow up with Bob", due_in_days=-1)


def _run_as_business(monkeypatch, business_id):
    """
    Points both config.BUSINESS_ID (what reminder_manager.get_reminders()
    actually filters by) and jobs.BUSINESS_ID (automation/jobs.py's own
    static-imported copy, used for the active-business check) at the same
    business - mirrors a real deployment, where both are always the same
    fixed value.
    """
    monkeypatch.setattr(config, "BUSINESS_ID", business_id)
    monkeypatch.setattr(jobs, "BUSINESS_ID", business_id)


def test_send_due_reminders_only_sends_for_this_deployments_business(
    isolated_db, monkeypatch
):

    _two_businesses_with_reminders(monkeypatch)

    sent = []
    monkeypatch.setattr(jobs, "send_message", _mock_send(sent))
    _run_as_business(monkeypatch, "bizA")

    asyncio.run(jobs.send_due_reminders())

    recipients = {to for to, _ in sent}
    assert recipients == {"+91100000001"}


def test_send_due_reminders_uses_real_reminder_text(isolated_db, monkeypatch):

    _two_businesses_with_reminders(monkeypatch)

    sent = []
    monkeypatch.setattr(jobs, "send_message", _mock_send(sent))
    _run_as_business(monkeypatch, "bizA")

    asyncio.run(jobs.send_due_reminders())

    assert len(sent) == 1
    _, message = sent[0]
    assert "Follow up with Alice" in message


def test_send_due_reminders_skips_when_business_not_active(
    isolated_db, monkeypatch
):

    _two_businesses_with_reminders(monkeypatch)

    sent = []
    monkeypatch.setattr(jobs, "send_message", _mock_send(sent))
    # No business registered under this id at all - the deployment's own
    # business isn't in the active registry (e.g. deactivated), so
    # nothing should be sent rather than falling back to unscoped.
    _run_as_business(monkeypatch, "biz_not_registered")

    asyncio.run(jobs.send_due_reminders())

    assert sent == []
