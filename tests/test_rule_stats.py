"""
Tests for automation/rule_stats.py - the per-rule performance tracking
that backs the Analytics page's Automation Rule Performance table (see
api/dashboard.py's dashboard_analytics()). Covers the upsert behavior of
record_rule_execution() (must not grow unbounded when a rule keeps
matching the same customer on every automation tick - see
automation/runner.py) and get_rule_performance()'s win-rate calculation
against crm.lead_manager's Closed Won status.
"""

from automation.manager import create_rule, set_enabled
from automation.rule_stats import record_rule_execution, get_rule_performance
from crm.lead_manager import update_lead
from database.db import get_conversation_connection


def _rule_data(name="Rule"):
    return {
        "name": name,
        "description": "",
        "enabled": True,
        "trigger_type": "lead_score",
        "condition_json": [{"field": "lead_score", "operator": ">=", "value": 80}],
        "action_json": [{"name": "create_reminder", "params": {"text": "Follow up", "days": 1}}],
    }


def test_record_rule_execution_creates_one_row_per_customer(isolated_db):
    rule_id = create_rule(_rule_data("Rule A"))

    record_rule_execution(rule_id, "Rule A", "biz1", "+91100000001")
    record_rule_execution(rule_id, "Rule A", "biz1", "+91100000002")

    conn = get_conversation_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM automation_rule_executions WHERE rule_id=?",
        (rule_id,)
    ).fetchone()[0]
    conn.close()

    assert count == 2


def test_record_rule_execution_upserts_on_repeat_match(isolated_db):
    # A rule that keeps matching the same customer on every automation
    # tick must not grow the table without bound - repeat matches update
    # one row's fire_count/last_fired_at instead of inserting a new row.
    rule_id = create_rule(_rule_data("Rule A"))

    for _ in range(5):
        record_rule_execution(rule_id, "Rule A", "biz1", "+91100000001")

    conn = get_conversation_connection()
    row = conn.execute(
        "SELECT COUNT(*) as cnt, MAX(fire_count) as fc "
        "FROM automation_rule_executions WHERE rule_id=?",
        (rule_id,)
    ).fetchone()
    conn.close()

    assert row["cnt"] == 1
    assert row["fc"] == 5


def test_get_rule_performance_includes_rules_with_zero_executions(isolated_db):
    rule_id = create_rule(_rule_data("Never Fired"))

    performance = get_rule_performance()

    assert len(performance) == 1
    assert performance[0]["rule_id"] == rule_id
    assert performance[0]["customers_matched"] == 0
    assert performance[0]["fire_count"] == 0
    assert performance[0]["won_count"] == 0
    assert performance[0]["win_rate"] == 0.0


def test_get_rule_performance_computes_win_rate_from_closed_won_leads(isolated_db):
    rule_id = create_rule(_rule_data("High Value Lead"))

    record_rule_execution(rule_id, "High Value Lead", "biz1", "+91100000001")
    record_rule_execution(rule_id, "High Value Lead", "biz1", "+91100000002")

    # Only one of the two matched customers has since closed.
    update_lead("+91100000001", "Closed Won", "", confidence=90)
    update_lead("+91100000002", "Interested", "", confidence=50)

    performance = get_rule_performance()

    rule_row = next(r for r in performance if r["rule_id"] == rule_id)

    assert rule_row["customers_matched"] == 2
    assert rule_row["won_count"] == 1
    assert rule_row["win_rate"] == 50.0


def test_get_rule_performance_reflects_enabled_flag(isolated_db):
    rule_id = create_rule(_rule_data("Disabled Rule"))

    set_enabled(rule_id, False)

    performance = get_rule_performance()

    assert performance[0]["enabled"] is False


def test_get_rule_performance_returns_empty_list_when_no_rules(isolated_db):
    assert get_rule_performance() == []


def test_get_rule_performance_filters_to_one_business(isolated_db):
    # Two businesses, each with their own rule and their own execution -
    # get_rule_performance(business_id) must not leak Business B's rule
    # (or its executions) into Business A's performance view.
    rule_a = create_rule(_rule_data("Biz A Rule"), business_id="bizA")
    rule_b = create_rule(_rule_data("Biz B Rule"), business_id="bizB")

    record_rule_execution(rule_a, "Biz A Rule", "bizA", "+91100000001")
    record_rule_execution(rule_b, "Biz B Rule", "bizB", "+91100000002")

    performance_a = get_rule_performance("bizA")

    assert len(performance_a) == 1
    assert performance_a[0]["rule_id"] == rule_a
    assert performance_a[0]["customers_matched"] == 1

    performance_b = get_rule_performance("bizB")

    assert len(performance_b) == 1
    assert performance_b[0]["rule_id"] == rule_b
