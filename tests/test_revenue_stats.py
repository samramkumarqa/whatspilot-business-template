"""
Tests for analytics/revenue_stats.py - the Won Revenue Trend chart on the
Analytics page. Covers month-bucket generation (_last_n_months) and
get_won_revenue_trend()'s attribution of a customer's tracked
opportunities.estimated_value to the month they most recently became
Closed Won (see crm.lead_manager's leads.status / lead_history).
"""

from datetime import datetime

import config
from analytics.revenue_stats import get_won_revenue_trend, _last_n_months
from crm.customer_mapping import save_customer_number, save_mapping
from crm.lead_manager import update_lead
from crm.opportunity_manager import add_opportunity


def _seed_customer(user_id, business_id, business_phone, customer_phone, name):
    save_customer_number(user_id, business_phone, business_id)
    save_mapping(
        customer_phone=customer_phone,
        business_phone=business_phone,
        customer_name=name,
    )


# get_won_revenue_trend() resolves business_id via get_business_id(user_id)
# (the *registered* business_id from _seed_customer() above), while
# add_opportunity()/update_lead() stamp whichever business_id
# config.BUSINESS_ID currently points at - these two have to match, same
# as they always do in a real deployment, so every write below happens
# through these business-scoped wrappers instead of calling the CRM
# functions directly.
def _add_opportunity_for(monkeypatch, business_id, *args, **kwargs):
    monkeypatch.setattr(config, "BUSINESS_ID", business_id)
    add_opportunity(*args, **kwargs)


def _update_lead_for(monkeypatch, business_id, *args, **kwargs):
    monkeypatch.setattr(config, "BUSINESS_ID", business_id)
    update_lead(*args, **kwargs)


def test_last_n_months_returns_n_months_ending_with_current_month():
    labels, keys = _last_n_months(6)

    assert len(labels) == 6
    assert len(keys) == 6

    current_key = datetime.now().strftime("%Y-%m")
    assert keys[-1] == current_key


def test_last_n_months_wraps_year_boundary():
    # Exercise the December -> January rollback regardless of what month
    # the test happens to run in, by asking for enough months back that
    # it must cross at least one year boundary either way.
    labels, keys = _last_n_months(13)

    assert len(set(keys)) == 13  # no duplicate month keys
    # Consecutive keys must be exactly one calendar month apart.
    for i in range(1, len(keys)):
        y1, m1 = map(int, keys[i - 1].split("-"))
        y2, m2 = map(int, keys[i].split("-"))
        assert (y2 * 12 + m2) - (y1 * 12 + m1) == 1


def test_unknown_user_returns_zeroed_trend(isolated_db):
    trend = get_won_revenue_trend("no-such-user", months=3)

    assert len(trend["labels"]) == 3
    assert trend["values"] == [0, 0, 0]


def test_no_closed_won_customers_returns_zeroed_trend(isolated_db, monkeypatch):
    _seed_customer("u1", "biz1", "+10000000000", "+919962824442", "Saranya S")

    # Still just "Interested" - not Closed Won.
    _update_lead_for(monkeypatch, "biz1", "+919962824442", "Interested", "", confidence=50)
    _add_opportunity_for(monkeypatch, "biz1", "+919962824442", "New Sale", confidence=70, reason="", estimated_value=50000)

    trend = get_won_revenue_trend("u1", months=3)

    assert trend["values"] == [0, 0, 0]


def test_closed_won_customer_revenue_lands_in_current_month(isolated_db, monkeypatch):
    _seed_customer("u1", "biz1", "+10000000000", "+919962824442", "Saranya S")

    _add_opportunity_for(monkeypatch, "biz1", "+919962824442", "New Sale", confidence=90, reason="", estimated_value=150000)
    _update_lead_for(monkeypatch, "biz1", "+919962824442", "Closed Won", "", confidence=90)

    trend = get_won_revenue_trend("u1", months=3)

    # Closed just now -> falls into the last (current) month bucket.
    assert trend["values"][-1] == 150000
    assert trend["values"][:-1] == [0, 0]


def test_revenue_sums_multiple_opportunities_for_same_customer(isolated_db, monkeypatch):
    _seed_customer("u1", "biz1", "+10000000000", "+919962824442", "Saranya S")

    _add_opportunity_for(monkeypatch, "biz1", "+919962824442", "New Sale", confidence=90, reason="", estimated_value=100000)
    _add_opportunity_for(monkeypatch, "biz1", "+919962824442", "Upsell", confidence=80, reason="", estimated_value=25000)
    _update_lead_for(monkeypatch, "biz1", "+919962824442", "Closed Won", "", confidence=90)

    trend = get_won_revenue_trend("u1", months=1)

    assert trend["values"] == [125000]


def test_revenue_only_counts_won_customers_scoped_to_business(isolated_db, monkeypatch):
    _seed_customer("u1", "biz1", "+10000000000", "+919962824442", "Won Customer")
    _seed_customer("u2", "biz2", "+20000000000", "+916374000275", "Other Business Customer")

    _add_opportunity_for(monkeypatch, "biz1", "+919962824442", "New Sale", confidence=90, reason="", estimated_value=100000)
    _update_lead_for(monkeypatch, "biz1", "+919962824442", "Closed Won", "", confidence=90)

    _add_opportunity_for(monkeypatch, "biz2", "+916374000275", "New Sale", confidence=90, reason="", estimated_value=999999)
    _update_lead_for(monkeypatch, "biz2", "+916374000275", "Closed Won", "", confidence=90)

    trend = get_won_revenue_trend("u1", months=1)

    # Only u1's business (biz1) customer's revenue should be counted.
    assert trend["values"] == [100000]
