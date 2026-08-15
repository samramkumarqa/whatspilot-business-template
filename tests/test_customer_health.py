"""
Tests for analytics/customer_health.py's get_customer_health_dashboard() -
rewritten in this optimization pass to batch its leads/reminders/last-seen
lookups (one query each for every customer) instead of doing 3+ queries
PER CUSTOMER plus a redundant get_business_id() call on every loop
iteration. No tests existed for this module before, so this covers both
the "no customers" / "unknown user" edge cases and that the batched
rewrite still produces the same health classifications as the original
per-customer version.
"""

from datetime import datetime, timedelta

from analytics.customer_health import get_customer_health_dashboard
from crm.customer_mapping import save_customer_number, save_mapping
from crm.lead_manager import update_lead_intelligence
from reminder_manager import upsert_reminder
from database.db import get_conversation_connection


def _seed_business(user_id="u1", business_id="business_001", business_phone="+10000000000"):
    save_customer_number(user_id, business_phone, business_id)
    return business_phone


def _seed_conversation(business_id, customer_phone, created_at):
    conn = get_conversation_connection()
    conn.execute(
        """
        INSERT INTO conversations (phone, role, content, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (f"{business_id}:{customer_phone}", "user", "hi", created_at)
    )
    conn.commit()
    conn.close()


def test_dashboard_returns_zeros_for_unknown_user(isolated_db):
    dashboard = get_customer_health_dashboard("ghost")

    assert dashboard == {
        "healthy": 0,
        "good": 0,
        "needs_attention": 0,
        "at_risk": 0,
        "average_score": 0,
    }


def test_dashboard_returns_zeros_for_business_with_no_customers(isolated_db):
    _seed_business()

    dashboard = get_customer_health_dashboard("u1")

    assert dashboard["healthy"] == 0
    assert dashboard["good"] == 0
    assert dashboard["needs_attention"] == 0
    assert dashboard["at_risk"] == 0
    assert dashboard["average_score"] == 0


def _full_analysis(**overrides):
    """
    update_lead_intelligence() writes every one of these keys
    unconditionally (see crm/lead_manager.py) - in production
    ai/lead_intelligence.py's analyse_conversation() always returns a
    fully-populated dict, so tests need to supply the same shape.
    """

    analysis = {
        "status": "New",
        "confidence": 50,
        "summary": "",
        "lead_score": 40,
        "intent": "General Inquiry",
        "buying_stage": "Interested",
        "sentiment": "Neutral",
        "objection": "None",
        "priority": "Medium",
        "probability": 20,
        "next_action": "Manual Review",
        "follow_up_days": 1,
        "tags": [],
    }
    analysis.update(overrides)
    return analysis


def test_dashboard_classifies_customers_by_health_score(isolated_db):
    business_phone = _seed_business()

    # A healthy, engaged customer: strong lead score, "Customer" buying
    # stage, positive sentiment, no overdue reminders, seen recently.
    save_mapping("+20000000001", business_phone)
    update_lead_intelligence(
        "+20000000001",
        _full_analysis(
            status="Closed Won",
            lead_score=90,
            buying_stage="Customer",
            sentiment="Positive",
        ),
    )
    _seed_conversation(
        "business_001", "+20000000001",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    # An at-risk customer: no lead record at all (defaults apply), an
    # overdue reminder, and never seen in conversations.
    save_mapping("+20000000002", business_phone)
    upsert_reminder("+20000000002", "Follow up", days=-5)

    dashboard = get_customer_health_dashboard("u1")

    assert dashboard["healthy"] == 1
    assert dashboard["at_risk"] == 1
    assert dashboard["good"] == 0
    assert dashboard["needs_attention"] == 0
    assert dashboard["average_score"] > 0


def test_dashboard_handles_customer_with_no_lead_record(isolated_db):
    """
    A customer with no row in `leads` at all should fall back to
    DEFAULT_LEAD (the same behavior get_lead() gives a single customer),
    not be silently dropped from the batched leads_by_phone lookup.
    """

    business_phone = _seed_business()
    save_mapping("+20000000003", business_phone)

    dashboard = get_customer_health_dashboard("u1")

    total = (
        dashboard["healthy"]
        + dashboard["good"]
        + dashboard["needs_attention"]
        + dashboard["at_risk"]
    )
    assert total == 1


def test_dashboard_last_seen_only_matches_this_business(isolated_db):
    """
    The batched last-seen query joins on "{business_id}:{customer_phone}"
    conversation ids scoped to this business - a conversation row logged
    under a DIFFERENT business_id for the same raw phone number must not
    be picked up (would incorrectly mark a never-seen customer as
    recently active).
    """

    business_phone = _seed_business()
    save_mapping("+20000000004", business_phone)

    # Conversation logged under an unrelated business_id, same phone.
    _seed_conversation(
        "business_999", "+20000000004",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    dashboard = get_customer_health_dashboard("u1")

    # With no lead, no reminders, and no matching conversation, this
    # customer should be scored as never-seen (last_seen_days=999) and
    # land in at_risk, not healthy/good.
    assert dashboard["at_risk"] == 1
    assert dashboard["healthy"] == 0
    assert dashboard["good"] == 0
