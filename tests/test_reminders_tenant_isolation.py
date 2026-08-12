"""
Regression tests for a real cross-tenant data leak: GET /reminders (the
Follow-ups page and dashboard bell badge), GET+DELETE /reminders/stale,
and POST /reminders/{id}/complete all used to run with no business
scoping at all - any logged-in business owner saw and could mutate every
other business's reminders. See reminder_manager.get_reminders(),
find_stale_reminders(), delete_stale_reminders(), and
get_reminder_customer_phone() for the fix (all now take/resolve a
business_phone and filter via a customer_mapping JOIN), and
api/misc.py's GET /reminders + api/reminders.py's routes for where that's
enforced at the HTTP layer via auth.enforce_tenant_access() /
enforce_tenant_access_for_customer().

These tests exercise the business-scoping logic directly at the
reminder_manager layer (same style as tests/test_tenant_isolation.py),
rather than spinning up a full session-authenticated HTTP client.
"""

from crm.customer_mapping import save_customer_number, save_mapping
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


def _two_businesses_with_reminders():
    _register_business("u1", "bizA", "+10000000001")
    _register_business("u2", "bizB", "+10000000002")

    _attach_customer("+91100000001", "+10000000001", "Alice")
    _attach_customer("+91100000002", "+10000000002", "Bob")

    create_reminder("+91100000001", "Follow up with Alice", due_in_days=-1)
    create_reminder("+91100000002", "Follow up with Bob", due_in_days=-1)


def test_get_reminders_unscoped_still_returns_everyone_for_internal_jobs(isolated_db):
    """
    business_phone=None (the default) is only meant for the internal
    send_due_reminders() scheduled job, which legitimately dispatches
    across every tenant - this must keep working unscoped.
    """

    _two_businesses_with_reminders()

    all_reminders = get_reminders()

    texts = {r["reminder_text"] for r in all_reminders}
    assert "Follow up with Alice" in texts
    assert "Follow up with Bob" in texts


def test_get_reminders_scoped_to_one_business_excludes_the_other(isolated_db):

    _two_businesses_with_reminders()

    biz_a_reminders = get_reminders("+10000000001")
    biz_b_reminders = get_reminders("+10000000002")

    assert [r["reminder_text"] for r in biz_a_reminders] == ["Follow up with Alice"]
    assert [r["reminder_text"] for r in biz_b_reminders] == ["Follow up with Bob"]


def test_get_reminders_unknown_business_phone_returns_nothing(isolated_db):

    _two_businesses_with_reminders()

    assert get_reminders("+19999999999") == []


def test_find_stale_reminders_scoped_to_one_business(isolated_db):

    _register_business("u1", "bizA", "+10000000001")
    _register_business("u2", "bizB", "+10000000002")

    _attach_customer("+91100000001", "+10000000001", "Alice")
    _attach_customer("+91100000002", "+10000000002", "Bob")

    from database.db import get_crm_connection

    conn = get_crm_connection()
    conn.execute(
        """
        INSERT INTO reminders
            (customer_phone, reminder_text, due_date, source_rule_id, source_rule_name)
        VALUES
            ('+91100000001', 'Old text', '2020-01-01', 999, 'Deleted Rule A'),
            ('+91100000002', 'Old text', '2020-01-01', 998, 'Deleted Rule B')
        """
    )
    conn.commit()
    conn.close()

    stale_a = find_stale_reminders("+10000000001")
    stale_b = find_stale_reminders("+10000000002")

    assert [s["source_rule_name"] for s in stale_a] == ["Deleted Rule A"]
    assert [s["source_rule_name"] for s in stale_b] == ["Deleted Rule B"]


def test_delete_stale_reminders_scoped_does_not_touch_other_business(isolated_db):

    _register_business("u1", "bizA", "+10000000001")
    _register_business("u2", "bizB", "+10000000002")

    _attach_customer("+91100000001", "+10000000001", "Alice")
    _attach_customer("+91100000002", "+10000000002", "Bob")

    from database.db import get_crm_connection

    conn = get_crm_connection()
    conn.execute(
        """
        INSERT INTO reminders
            (customer_phone, reminder_text, due_date, source_rule_id, source_rule_name)
        VALUES
            ('+91100000001', 'Old text', '2020-01-01', 999, 'Deleted Rule A'),
            ('+91100000002', 'Old text', '2020-01-01', 998, 'Deleted Rule B')
        """
    )
    conn.commit()
    conn.close()

    deleted = delete_stale_reminders("+10000000001")

    assert deleted == 1

    # Business A's stale reminder is gone, business B's is untouched.
    assert find_stale_reminders("+10000000001") == []
    assert len(find_stale_reminders("+10000000002")) == 1


def test_get_reminder_customer_phone_resolves_owner(isolated_db):

    _two_businesses_with_reminders()

    alice_reminder = next(
        r for r in get_reminders("+10000000001")
        if r["reminder_text"] == "Follow up with Alice"
    )

    assert get_reminder_customer_phone(alice_reminder["id"]) == "+91100000001"


def test_get_reminder_customer_phone_unknown_id_returns_none(isolated_db):

    assert get_reminder_customer_phone(999999) is None
