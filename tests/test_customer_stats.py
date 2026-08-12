"""
analytics/customer_stats.py's search_customers() backs the dashboard's
conversation search box (see api/customer.py's /customer-search/{user_id}
and templates/dashboard.html's searchCustomers()). It's expected to match
a customer if the query appears in their phone number, their name, or
anywhere in their conversation history - tested here against the
isolated_db fixture with real seeded data rather than mocks.
"""

from crm.customer_mapping import save_customer_number, save_mapping
from conversations import add_message
from crm.opportunity_manager import add_opportunity
from analytics.customer_stats import (
    search_customers,
    get_customer_stats,
    get_dashboard_metrics,
)


def _seed_customer(user_id, business_id, business_phone, customer_phone, name, message):
    save_customer_number(user_id, business_phone, business_id)
    save_mapping(
        customer_phone=customer_phone,
        business_phone=business_phone,
        customer_name=name,
    )
    add_message(f"{business_id}:{customer_phone}", "user", message)


def test_search_by_phone_number(isolated_db):
    _seed_customer("u1", "biz1", "+10000000000", "+919962824442", "Saranya S", "hi there")
    _seed_customer("u1", "biz1", "+10000000000", "+916374000275", "Shanthi", "hello")

    results = search_customers("u1", "9962824442")

    assert [c["phone"] for c in results] == ["+919962824442"]


def test_search_by_name_is_case_insensitive(isolated_db):
    _seed_customer("u1", "biz1", "+10000000000", "+919962824442", "Saranya S", "hi there")
    _seed_customer("u1", "biz1", "+10000000000", "+916374000275", "Shanthi", "hello")

    results = search_customers("u1", "saranya")

    assert [c["phone"] for c in results] == ["+919962824442"]


def test_search_by_message_content_matches_full_history_not_just_last_message(isolated_db):
    _seed_customer("u1", "biz1", "+10000000000", "+919962824442", "Saranya S", "what is the price?")
    _seed_customer("u1", "biz1", "+10000000000", "+916374000275", "Shanthi", "hello there")

    # A second, more recent message from the same customer - last_message
    # in get_customer_stats() would only be this one, not the earlier
    # "price" message, so this proves search covers the whole thread.
    add_message("biz1:+919962824442", "assistant", "Our course starts Monday")

    results = search_customers("u1", "price")

    assert [c["phone"] for c in results] == ["+919962824442"]


def test_search_empty_query_returns_everyone(isolated_db):
    _seed_customer("u1", "biz1", "+10000000000", "+919962824442", "Saranya S", "hi")
    _seed_customer("u1", "biz1", "+10000000000", "+916374000275", "Shanthi", "hello")

    all_customers = get_customer_stats("u1")
    results = search_customers("u1", "")

    assert len(results) == len(all_customers) == 2


def test_search_no_match_returns_empty_list(isolated_db):
    _seed_customer("u1", "biz1", "+10000000000", "+919962824442", "Saranya S", "hi")

    assert search_customers("u1", "zzzznomatchzzzz") == []


def test_search_unknown_user_returns_empty_list(isolated_db):
    assert search_customers("no-such-user", "anything") == []


# ---------------------------------------------------------------------
# get_dashboard_metrics() - backs the dashboard header's 👥/💬/💰 stats.
#
# Regression context: the header's 💰 Opportunities count used to be
# computed client-side in dashboard.html as
# customers.filter(lead_score >= 60).length, a heuristic with no actual
# connection to the opportunities table - the same table the Opportunity
# Pipeline chart reads from. These tests pin down that
# get_dashboard_metrics()'s open_opportunities instead reflects real rows
# from that table, and that customers/messages match what
# get_customer_stats() (the inbox list) would independently compute.
# ---------------------------------------------------------------------

def test_dashboard_metrics_counts_customers_and_messages(isolated_db):
    _seed_customer("u1", "biz1", "+10000000000", "+919962824442", "Saranya S", "hi there")
    _seed_customer("u1", "biz1", "+10000000000", "+916374000275", "Shanthi", "hello")
    add_message("biz1:+919962824442", "assistant", "Welcome!")

    metrics = get_dashboard_metrics("u1")

    assert metrics["customers"] == 2
    # 2 seeded user messages + 1 assistant reply
    assert metrics["messages"] == 3


def test_dashboard_metrics_open_opportunities_reflects_real_opportunities_table(isolated_db):
    _seed_customer("u1", "biz1", "+10000000000", "+919962824442", "Saranya S", "hi there")
    _seed_customer("u1", "biz1", "+10000000000", "+916374000275", "Shanthi", "hello")

    # Neither seeded customer has a lead_score set at all (defaults to 0),
    # so the old lead_score >= 60 heuristic would have reported 0 here even
    # though there are 2 real open opportunities tracked below.
    add_opportunity("+919962824442", "Upsell", confidence=90, reason="asked about upgrade")
    add_opportunity("+916374000275", "New Sale", confidence=70, reason="ready to buy", estimated_value=150000)

    metrics = get_dashboard_metrics("u1")

    assert metrics["open_opportunities"] == 2


def test_dashboard_metrics_excludes_closed_opportunities(isolated_db):
    _seed_customer("u1", "biz1", "+10000000000", "+919962824442", "Saranya S", "hi there")

    add_opportunity("+919962824442", "Upsell", confidence=90, reason="asked about upgrade")

    from database.db import get_crm_connection
    conn = get_crm_connection()
    conn.execute("UPDATE opportunities SET status='Won' WHERE customer_phone=?", ("+919962824442",))
    conn.commit()
    conn.close()

    metrics = get_dashboard_metrics("u1")

    assert metrics["open_opportunities"] == 0


def test_dashboard_metrics_unknown_user_returns_zeros(isolated_db):
    metrics = get_dashboard_metrics("no-such-user")

    assert metrics == {
        "customers": 0,
        "messages": 0,
        "today_messages": 0,
        "open_opportunities": 0,
    }
