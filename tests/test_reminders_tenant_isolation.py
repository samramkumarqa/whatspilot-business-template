"""
Regression tests for a real cross-tenant data leak: GET /reminders (the
Follow-ups page and dashboard bell badge), GET+DELETE /reminders/stale,
and POST /reminders/{id}/complete all used to run with no business
scoping at all - any logged-in business owner saw and could mutate every
other business's reminders.

Originally fixed via an optional business_phone parameter joined through
customer_mapping (business_phone -> customer_phone). That join was itself
a cross-tenant risk: customer_mapping only ever records a customer's
*current* business (save_mapping() overwrites it), so if the same phone
number ever contacted two different businesses, the mapping-based join
would attribute one business's historical reminders to whichever
business the phone is mapped to *now*. reminder_manager.py now stamps a
business_id on every reminder at write time (this deployment's own
config.BUSINESS_ID - see migrations/add_business_id_to_crm_tables.py's
module docstring) and filters reads by it directly - no business_phone
parameter needed anymore, since there's only ever one correct scope for
any caller running inside a given deployment.

These tests exercise the business-scoping logic directly at the
reminder_manager layer (same style as tests/test_tenant_isolation.py),
rather than spinning up a full session-authenticated HTTP client.
"""

import config
from crm.customer_mapping import save_customer_number, save_mapping
from database.db import get_crm_connection
from reminder_manager import (
    create_reminder,
    get_reminders,
    find_stale_reminders,
    delete_stale_reminders,
    get_reminder_customer_phone,
)


def _register_business(user_id, business_id, whatsapp_number):
    save_customer_number(user_id, whatsapp_number, business_id)


def _attach_customer(customer_phone, business_phone, name=None):
    save_mapping(customer_phone, business_phone, name)


def _create_reminder_as(monkeypatch, business_id, customer_phone, text):
    """
    Creates a reminder stamped with the given business_id, by pointing
    config.BUSINESS_ID at it for the duration of this one call - mirrors
    what actually happens in production, where each deployment's
    BUSINESS_ID is fixed and every reminder it creates is naturally
    stamped with its own business_id.
    """
    monkeypatch.setattr(config, "BUSINESS_ID", business_id)
    create_reminder(customer_phone, text, due_in_days=-1)


def _two_businesses_with_reminders(monkeypatch):
    _register_business("u1", "bizA", "+10000000001")
    _register_business("u2", "bizB", "+10000000002")

    _attach_customer("+91100000001", "+10000000001", "Alice")
    _attach_customer("+91100000002", "+10000000002", "Bob")

    _create_reminder_as(monkeypatch, "bizA", "+91100000001", "Follow up with Alice")
    _create_reminder_as(monkeypatch, "bizB", "+91100000002", "Follow up with Bob")


def test_get_reminders_scoped_to_one_business_excludes_the_other(isolated_db, monkeypatch):

    _two_businesses_with_reminders(monkeypatch)

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    biz_a_reminders = get_reminders()

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    biz_b_reminders = get_reminders()

    assert [r["reminder_text"] for r in biz_a_reminders] == ["Follow up with Alice"]
    assert [r["reminder_text"] for r in biz_b_reminders] == ["Follow up with Bob"]


def test_get_reminders_unknown_business_returns_nothing(isolated_db, monkeypatch):

    _two_businesses_with_reminders(monkeypatch)

    monkeypatch.setattr(config, "BUSINESS_ID", "biz_not_registered")

    assert get_reminders() == []


def test_find_stale_reminders_scoped_to_one_business(isolated_db, monkeypatch):

    _register_business("u1", "bizA", "+10000000001")
    _register_business("u2", "bizB", "+10000000002")

    _attach_customer("+91100000001", "+10000000001", "Alice")
    _attach_customer("+91100000002", "+10000000002", "Bob")

    conn = get_crm_connection()
    conn.execute(
        """
        INSERT INTO reminders
            (customer_phone, business_id, reminder_text, due_date, source_rule_id, source_rule_name)
        VALUES
            ('+91100000001', 'bizA', 'Old text', '2020-01-01', 999, 'Deleted Rule A'),
            ('+91100000002', 'bizB', 'Old text', '2020-01-01', 998, 'Deleted Rule B')
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    stale_a = find_stale_reminders()

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    stale_b = find_stale_reminders()

    assert [s["source_rule_name"] for s in stale_a] == ["Deleted Rule A"]
    assert [s["source_rule_name"] for s in stale_b] == ["Deleted Rule B"]


def test_delete_stale_reminders_scoped_does_not_touch_other_business(isolated_db, monkeypatch):

    _register_business("u1", "bizA", "+10000000001")
    _register_business("u2", "bizB", "+10000000002")

    _attach_customer("+91100000001", "+10000000001", "Alice")
    _attach_customer("+91100000002", "+10000000002", "Bob")

    conn = get_crm_connection()
    conn.execute(
        """
        INSERT INTO reminders
            (customer_phone, business_id, reminder_text, due_date, source_rule_id, source_rule_name)
        VALUES
            ('+91100000001', 'bizA', 'Old text', '2020-01-01', 999, 'Deleted Rule A'),
            ('+91100000002', 'bizB', 'Old text', '2020-01-01', 998, 'Deleted Rule B')
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")

    deleted = delete_stale_reminders()

    assert deleted == 1

    # Business A's stale reminder is gone, business B's is untouched.
    assert find_stale_reminders() == []

    monkeypatch.setattr(config, "BUSINESS_ID", "bizB")
    assert len(find_stale_reminders()) == 1


def test_get_reminder_customer_phone_resolves_owner(isolated_db, monkeypatch):

    _two_businesses_with_reminders(monkeypatch)

    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    alice_reminder = next(
        r for r in get_reminders()
        if r["reminder_text"] == "Follow up with Alice"
    )

    assert get_reminder_customer_phone(alice_reminder["id"]) == "+91100000001"


def test_get_reminder_customer_phone_unknown_id_returns_none(isolated_db):

    assert get_reminder_customer_phone(999999) is None
