"""
Regression tests for Phase 1 data isolation: proving Business A's rules,
rule executions, leads, opportunities, and conversations never leak into
Business B's queries. See automation/database.py, automation/manager.py,
automation/runner.py, api/automation.py, and api/dashboard.py for the
production code these tests cover.

Two businesses are registered per test via save_customer_number() +
save_mapping() - the same tenant-registry/customer-routing tables the
real app uses (crm/customer_mapping.py).
"""

import asyncio

from automation.database import get_all_rules, create_rule as db_create_rule
from automation.manager import create_rule as mgr_create_rule
from automation.rule_stats import record_rule_execution, get_rule_performance
from automation.runner import run_automation
from api.dashboard import _build_dashboard_analytics
from crm.customer_mapping import save_customer_number, save_mapping
from crm.lead_manager import update_lead
from crm.opportunity_manager import add_opportunity
from conversations import add_message


def _register_business(user_id, business_id, whatsapp_number):
    save_customer_number(user_id, whatsapp_number, business_id)


def _attach_customer(customer_phone, business_phone, business_id, name=None):
    save_mapping(customer_phone, business_phone, name)


# ---------------------------------------------------------------------
# automation/database.py - get_all_rules(business_id) scoping
# ---------------------------------------------------------------------

def _rule_data(name="Rule"):
    return {
        "name": name,
        "description": "",
        "enabled": True,
        "trigger_type": "lead_score",
        "condition_json": [{"field": "lead_score", "operator": ">=", "value": 80}],
        "action_json": [{"name": "create_reminder", "params": {"text": "Follow up", "days": 1}}],
    }


def test_get_all_rules_scoped_to_one_business(isolated_db):
    rule_a = db_create_rule({**_rule_data("Biz A Rule"), "business_id": "bizA"})
    rule_b = db_create_rule({**_rule_data("Biz B Rule"), "business_id": "bizB"})

    rules_a = get_all_rules("bizA")
    rules_b = get_all_rules("bizB")

    assert [r["id"] for r in rules_a] == [rule_a]
    assert [r["id"] for r in rules_b] == [rule_b]


# ---------------------------------------------------------------------
# automation/runner.py - loops over active businesses, evaluating each
# business's rules against only that business's customers.
# ---------------------------------------------------------------------

def test_runner_only_fires_this_deployments_own_business_rules(isolated_db, monkeypatch):
    """
    Every business-portal deployment shares one Postgres database with
    every other customer's deployment (see config.py's BUSINESS_ID) -
    this proves automation/runner.py only ever fires rules for its own
    configured business, even when a second, unrelated business is also
    active in that same shared database. Without the BUSINESS_ID filter
    in run_automation(), this deployment would also fire bizB's rules
    against bizB's customers - a real cross-customer leak, not just a
    hypothetical one, since get_active_businesses() has no idea which
    deployment is asking.
    """
    import config

    _register_business("u1", "bizA", "+10000000001")
    _register_business("u2", "bizB", "+10000000002")

    _attach_customer("+91100000001", "+10000000001", "bizA", "Alice")
    _attach_customer("+91100000002", "+10000000002", "bizB", "Bob")

    # get_customer_stats() (which evaluate_rule() calls) builds its
    # customer list from the conversations table, not customer_mapping -
    # a conversation row is what actually makes a customer visible to
    # automation.
    add_message("bizA:+91100000001", "user", "Hi, I'm interested")
    add_message("bizB:+91100000002", "user", "Hi, tell me more")

    # "Closed Won" + confidence=90 -> lead_score 96 (see
    # ai/lead_ai.py's calculate_lead_score), comfortably matching both
    # rules' lead_score >= 80 condition.
    update_lead("+91100000001", "Closed Won", "", confidence=90)
    update_lead("+91100000002", "Closed Won", "", confidence=90)

    rule_a = mgr_create_rule(_rule_data("Biz A Rule"), "bizA")
    rule_b = mgr_create_rule(_rule_data("Biz B Rule"), "bizB")

    # execute_actions (creates reminders) isn't the point of this test -
    # stub it so the test only asserts on which customers matched which
    # rule.
    monkeypatch.setattr("automation.runner.execute_actions", lambda rule, matched: None)

    # This deployment is bizA's - bizB is a real, active business in the
    # same shared database, but not this deployment's own.
    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    monkeypatch.setattr("automation.runner.BUSINESS_ID", "bizA")

    run_automation()

    performance_a = get_rule_performance("bizA")
    performance_b = get_rule_performance("bizB")

    assert len(performance_a) == 1
    assert performance_a[0]["rule_id"] == rule_a
    assert performance_a[0]["customers_matched"] == 1

    # bizB's rule shows up in its own performance listing (it exists,
    # regardless of whether anything ran it), but customers_matched is
    # 0 - proving this deployment's runner never even looked at bizB's
    # rules or customers, since it never evaluated the rule at all.
    assert len(performance_b) == 1
    assert performance_b[0]["rule_id"] == rule_b
    assert performance_b[0]["customers_matched"] == 0


# ---------------------------------------------------------------------
# api/dashboard.py - dashboard_analytics() business scoping
# ---------------------------------------------------------------------

def test_dashboard_analytics_does_not_leak_leads_across_businesses(isolated_db):

    _register_business("u1", "bizA", "+10000000001")
    _register_business("u2", "bizB", "+10000000002")

    _attach_customer("+91100000001", "+10000000001", "bizA", "Alice")
    _attach_customer("+91100000002", "+10000000002", "bizB", "Bob")

    update_lead("+91100000001", "Closed Won", "", confidence=95)
    update_lead("+91100000002", "New", "", confidence=10)

    result_a = _build_dashboard_analytics("u1")

    # Only Alice's lead should be counted for bizA - status_distribution
    # must not include Bob's "New" status.
    assert result_a["status_distribution"] == {"Closed Won": 1}


def test_dashboard_analytics_does_not_leak_opportunities_across_businesses(isolated_db):

    _register_business("u1", "bizA", "+10000000001")
    _register_business("u2", "bizB", "+10000000002")

    _attach_customer("+91100000001", "+10000000001", "bizA", "Alice")
    _attach_customer("+91100000002", "+10000000002", "bizB", "Bob")

    add_opportunity("+91100000001", "New Business", 80, "Interested", estimated_value=5000)
    add_opportunity("+91100000002", "New Business", 80, "Interested", estimated_value=9000)

    result_a = _build_dashboard_analytics("u1")

    assert result_a["pipeline"] == {"Open": 1}


def test_dashboard_analytics_does_not_leak_messages_across_businesses(isolated_db):

    _register_business("u1", "bizA", "+10000000001")
    _register_business("u2", "bizB", "+10000000002")

    add_message("bizA:+91100000001", "user", "Hi from Alice")
    add_message("bizB:+91100000002", "user", "Hi from Bob")
    add_message("bizB:+91100000002", "user", "Second message from Bob")

    result_a = _build_dashboard_analytics("u1")
    result_b = _build_dashboard_analytics("u2")

    total_messages_a = sum(day["count"] for day in result_a["message_trend"])
    total_messages_b = sum(day["count"] for day in result_b["message_trend"])

    assert total_messages_a == 1
    assert total_messages_b == 2


def test_dashboard_analytics_unregistered_user_id_returns_empty_shape(isolated_db):

    result = _build_dashboard_analytics("ghost")

    assert result["lead_distribution"] == {"Hot": 0, "Warm": 0, "Cold": 0}
    assert result["status_distribution"] == {}
    assert result["pipeline"] == {}
    assert result["message_trend"] == []
    assert result["rule_performance"] == []


# ---------------------------------------------------------------------
# automation/runner.py - fetches customer stats once per business, not
# once per rule (see automation/evaluator.py's evaluate_rule(customers=))
# ---------------------------------------------------------------------

def test_runner_fetches_customer_stats_once_per_business_not_per_rule(isolated_db, monkeypatch):

    _register_business("u1", "bizA", "+10000000001")
    _attach_customer("+91100000001", "+10000000001", "bizA", "Alice")
    add_message("bizA:+91100000001", "user", "Hi, I'm interested")
    update_lead("+91100000001", "Closed Won", "", confidence=90)

    # Three rules for the same business - before the fix,
    # evaluate_rule() would call get_customer_stats() once per rule (3
    # calls); the fix fetches it once in runner.py and passes it into
    # every evaluate_rule() call for that business instead.
    mgr_create_rule(_rule_data("Rule 1"), "bizA")
    mgr_create_rule(_rule_data("Rule 2"), "bizA")
    mgr_create_rule(_rule_data("Rule 3"), "bizA")

    call_count = {"n": 0}

    import analytics.customer_stats as customer_stats_module
    real_get_customer_stats = customer_stats_module.get_customer_stats

    def _counting_get_customer_stats(user_id):
        call_count["n"] += 1
        return real_get_customer_stats(user_id)

    monkeypatch.setattr(
        "automation.runner.get_customer_stats", _counting_get_customer_stats
    )
    monkeypatch.setattr("automation.runner.execute_actions", lambda rule, matched: None)

    import config
    monkeypatch.setattr(config, "BUSINESS_ID", "bizA")
    monkeypatch.setattr("automation.runner.BUSINESS_ID", "bizA")

    run_automation()

    assert call_count["n"] == 1


# ---------------------------------------------------------------------
# Phase 3 - session-level isolation via enforce_tenant_access()
# ---------------------------------------------------------------------
# Phase 1 above proved the *data layer* scopes correctly by business_id.
# These tests prove the *route layer* actually enforces who's allowed to
# ask for which business_id in the first place - a logged-in business
# owner hitting another business's user_id in the URL (e.g. by editing
# the hidden #userId field or hand-crafting a request) must be rejected
# before any of the Phase 1 scoping even runs. See auth.py's
# enforce_tenant_access() and api/dashboard.py, api/customer.py,
# api/automation.py's routes that call it.

import asyncio as _asyncio

import pytest
from fastapi import HTTPException

from tests.conftest import FakeRequest


def _owner_request(user_id):
    return FakeRequest({"role": "business_owner", "user_id": user_id})


def test_dashboard_route_blocks_business_owner_for_another_business(isolated_db):
    from api.dashboard import dashboard as dashboard_route

    _register_business("u1", "bizA", "+10000000001")
    _register_business("u2", "bizB", "+10000000002")

    # Their own business's dashboard works.
    result = _asyncio.run(dashboard_route("u1", _owner_request("u1")))
    assert result["status"] == "success"

    # Another business's dashboard does not.
    with pytest.raises(HTTPException) as exc_info:
        _asyncio.run(dashboard_route("u2", _owner_request("u1")))
    assert exc_info.value.status_code == 403


def test_stats_route_blocks_business_owner_for_another_business(isolated_db):
    from api.dashboard import stats as stats_route

    _register_business("u1", "bizA", "+10000000001")
    _register_business("u2", "bizB", "+10000000002")

    result = _asyncio.run(stats_route("u1", _owner_request("u1")))
    assert result["status"] == "success"

    with pytest.raises(HTTPException) as exc_info:
        _asyncio.run(stats_route("u2", _owner_request("u1")))
    assert exc_info.value.status_code == 403


def test_customer_details_route_blocks_business_owner_for_another_business(isolated_db):
    from api.customer import customer_details

    _register_business("u1", "bizA", "+10000000001")
    _register_business("u2", "bizB", "+10000000002")

    result = _asyncio.run(customer_details("u1", _owner_request("u1")))
    assert result["status"] == "success"

    with pytest.raises(HTTPException) as exc_info:
        _asyncio.run(customer_details("u2", _owner_request("u1")))
    assert exc_info.value.status_code == 403


def test_automation_list_rules_blocks_business_owner_for_another_business(isolated_db):
    from api.automation import list_rules

    _register_business("u1", "bizA", "+10000000001")
    _register_business("u2", "bizB", "+10000000002")

    result = _asyncio.run(list_rules("u1", _owner_request("u1")))
    assert result["status"] == "success"

    with pytest.raises(HTTPException) as exc_info:
        _asyncio.run(list_rules("u2", _owner_request("u1")))
    assert exc_info.value.status_code == 403



