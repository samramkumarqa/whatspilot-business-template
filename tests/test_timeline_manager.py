"""
Tests for timeline_manager.get_customer_timeline() - merges lead_history
(status transitions) and ai_activity (opportunities, tags, sales coach
tips, reminders, automation actions, manual notes) into one chronological
feed, replacing what used to be two separate dashboard panels ("Lead
Journey" and "Activity Log").

created_at columns default to SQLite's CURRENT_TIMESTAMP (1-second
resolution), and tests run far faster than a second - see the note in
test_crm_managers.py's test_update_lead_writes_history_entry. So instead
of relying on real function calls to naturally land at different
timestamps, these tests insert rows directly with explicit created_at
values, to deterministically exercise the collapsing/dedup logic.
"""

from database.db import get_crm_connection
from timeline_manager import get_customer_timeline


def _insert_history(phone, status, created_at, confidence=50, reason="", updated_by="AI"):
    conn = get_crm_connection()
    conn.execute(
        """
        INSERT INTO lead_history
        (customer_phone, status, confidence, reason, updated_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (phone, status, confidence, reason, updated_by, created_at)
    )
    conn.commit()
    conn.close()


def _insert_activity(phone, activity_type, title, details, created_at):
    conn = get_crm_connection()
    conn.execute(
        """
        INSERT INTO ai_activity
        (customer_phone, activity_type, title, details, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (phone, activity_type, title, details, created_at)
    )
    conn.commit()
    conn.close()


def test_collapses_repeated_status_with_no_real_change(isolated_db):
    # update_lead_intelligence() writes a lead_history row on every single
    # incoming message, even when the status doesn't change. Only the
    # actual transition (New -> Interested) should survive.
    phone = "+19998887777"

    _insert_history(phone, "New", "2026-08-01 10:00:00")
    _insert_history(phone, "New", "2026-08-01 10:01:00")
    _insert_history(phone, "New", "2026-08-01 10:02:00")
    _insert_history(phone, "Interested", "2026-08-01 10:03:00")
    _insert_history(phone, "Interested", "2026-08-01 10:04:00")

    timeline = get_customer_timeline(phone)

    status_entries = [t for t in timeline if t["type"] == "status_change"]
    assert len(status_entries) == 2
    assert {e["title"] for e in status_entries} == {
        "Status: New", "Status: Interested"
    }


def test_drops_status_change_already_covered_by_matching_activity(isolated_db):
    # A real status change writes to both tables at the same moment - the
    # lead_history row should be dropped in favor of the richer ai_activity
    # entry, instead of showing the same event twice.
    phone = "+19998887777"

    _insert_history(phone, "Qualified", "2026-08-01 10:00:00", updated_by="AI")
    _insert_activity(
        phone, "AI", "Customer Intelligence Updated",
        "Status: Qualified\nLead Score: 85",
        "2026-08-01 10:00:00"
    )

    timeline = get_customer_timeline(phone)

    assert len(timeline) == 1
    assert timeline[0]["type"] == "activity"
    assert timeline[0]["title"] == "Customer Intelligence Updated"


def test_keeps_status_change_with_no_matching_activity(isolated_db):
    # No matching ai_activity row at the same timestamp - keep the
    # transition itself so it isn't silently lost.
    phone = "+19998887777"

    _insert_history(phone, "Qualified", "2026-08-01 10:00:00", updated_by="AI")

    timeline = get_customer_timeline(phone)

    assert len(timeline) == 1
    assert timeline[0]["type"] == "status_change"
    assert timeline[0]["title"] == "Status: Qualified"


def test_merges_and_sorts_by_date_descending(isolated_db):
    phone = "+19998887777"

    _insert_history(phone, "New", "2026-08-01 09:00:00")
    _insert_activity(phone, "Sales Coach", "Follow up now", "details", "2026-08-01 09:30:00")
    _insert_history(phone, "Interested", "2026-08-01 10:00:00")
    _insert_activity(phone, "Tags", "Customer Tags Updated", "vip", "2026-08-01 11:00:00")

    timeline = get_customer_timeline(phone)

    dates = [t["date"] for t in timeline]
    assert dates == sorted(dates, reverse=True)
    assert dates[0] == "2026-08-01 11:00:00"


def test_manual_save_dedups_against_matching_activity(isolated_db):
    # POST /lead (api/customer.py) calls update_lead() then add_activity()
    # with type "Manual" - same dedup rule applies to manual saves as AI
    # ones.
    phone = "+19998887777"

    _insert_history(phone, "Proposal Sent", "2026-08-01 12:00:00", updated_by="Manual")
    _insert_activity(
        phone, "Manual", "Lead Updated Manually",
        "Status : Proposal Sent\n\nNotes :\nSent the quote",
        "2026-08-01 12:00:00"
    )

    timeline = get_customer_timeline(phone)

    assert len(timeline) == 1
    assert timeline[0]["activity_type"] == "Manual"
    assert timeline[0]["type"] == "activity"


def test_empty_for_customer_with_no_history_or_activity(isolated_db):
    assert get_customer_timeline("+10000000000") == []


def test_excludes_automation_rule_activity_entries(isolated_db):
    # "Add CRM Activity" rule actions log activity_type "Automation" -
    # generic boilerplate with no real signal, deliberately left out of
    # this merged timeline (unlike the AI-driven entries).
    phone = "+19998887777"

    _insert_activity(
        phone, "Automation", "Lead Follow-up Triggered",
        "Automation executed successfully.",
        "2026-08-01 09:00:00"
    )
    _insert_activity(
        phone, "Sales Coach", "Send pricing details", "details",
        "2026-08-01 09:30:00"
    )

    timeline = get_customer_timeline(phone)

    assert len(timeline) == 1
    assert timeline[0]["activity_type"] == "Sales Coach"


def test_dedup_is_scoped_per_customer(isolated_db):
    _insert_history("+19998887777", "Qualified", "2026-08-01 10:00:00", updated_by="AI")
    _insert_activity(
        "+11112223333", "AI", "Customer Intelligence Updated", "unrelated customer",
        "2026-08-01 10:00:00"
    )

    timeline = get_customer_timeline("+19998887777")

    # The other customer's activity at the same timestamp must not
    # suppress this customer's own status_change entry.
    assert len(timeline) == 1
    assert timeline[0]["type"] == "status_change"
