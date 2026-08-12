"""
automation/evaluator.py drives which customers match an automation rule's
conditions - this is the core of the automation engine (automation/runner.py
calls evaluate_rule() every minute per the scheduler in
automation/service.py). evaluate_condition() is pure and tested directly;
evaluate_rule() pulls customers via analytics.get_customer_stats(), so it's
tested against the isolated_db fixture with real seeded data.
"""

from automation.evaluator import evaluate_condition, evaluate_rule
from crm.customer_mapping import save_customer_number, save_mapping
from crm.lead_manager import update_lead
from conversations import add_message


# ---------------------------------------------------------------------------
# evaluate_condition - pure function, one comparison at a time
# ---------------------------------------------------------------------------

def test_numeric_operators():
    customer = {"lead_score": 75}
    assert evaluate_condition(customer, {"field": "lead_score", "operator": ">=", "value": 75})
    assert not evaluate_condition(customer, {"field": "lead_score", "operator": ">", "value": 75})
    assert evaluate_condition(customer, {"field": "lead_score", "operator": "<=", "value": 75})
    assert not evaluate_condition(customer, {"field": "lead_score", "operator": "<", "value": 75})


def test_equality_operators_compare_as_strings():
    customer = {"status": "Interested"}
    assert evaluate_condition(customer, {"field": "status", "operator": "=", "value": "Interested"})
    assert evaluate_condition(customer, {"field": "status", "operator": "==", "value": "Interested"})
    assert evaluate_condition(customer, {"field": "status", "operator": "!=", "value": "Qualified"})
    assert not evaluate_condition(customer, {"field": "status", "operator": "!=", "value": "Interested"})


def test_contains_operator_is_case_insensitive():
    customer = {"intent": "Pricing Inquiry"}
    assert evaluate_condition(customer, {"field": "intent", "operator": "contains", "value": "pricing"})
    assert not evaluate_condition(customer, {"field": "intent", "operator": "contains", "value": "refund"})


def test_missing_field_returns_false_not_error():
    customer = {"lead_score": 75}
    assert not evaluate_condition(customer, {"field": "does_not_exist", "operator": ">=", "value": 1})


def test_type_mismatch_is_handled_gracefully():
    # Comparing a string field with a numeric operator would normally raise
    # TypeError - evaluate_condition should catch it and return False rather
    # than crash the whole rule evaluation loop.
    customer = {"status": "Interested"}
    assert not evaluate_condition(customer, {"field": "status", "operator": ">=", "value": 50})


def test_numeric_operators_coerce_string_values():
    # Regression test: the rule builder's condition-value input is a plain
    # text field, so real rules created through the UI store "value" as a
    # string (e.g. "80") even for numeric fields like lead_score. Before this
    # fix, `value >= target` was `90 >= "80"`, which raises TypeError in
    # Python and got silently swallowed as False - meaning every numeric
    # condition created through the UI never matched anything.
    customer = {"lead_score": 90}
    assert evaluate_condition(customer, {"field": "lead_score", "operator": ">=", "value": "80"})
    assert evaluate_condition(customer, {"field": "lead_score", "operator": ">", "value": "80"})
    assert not evaluate_condition(customer, {"field": "lead_score", "operator": "<", "value": "80"})

    customer_days = {"last_seen_days": 5}
    assert evaluate_condition(customer_days, {"field": "last_seen_days", "operator": "<=", "value": "7"})
    assert not evaluate_condition(customer_days, {"field": "last_seen_days", "operator": ">=", "value": "7"})


# ---------------------------------------------------------------------------
# evaluate_rule - end to end against real seeded data
# ---------------------------------------------------------------------------

def _seed_customer(user_id, business_id, business_phone, customer_phone, lead_score, status="Interested"):
    save_customer_number(user_id, business_phone, business_id)
    save_mapping(customer_phone=customer_phone, business_phone=business_phone)
    add_message(f"{business_id}:{customer_phone}", "user", "hello")
    update_lead(
        customer_phone=customer_phone,
        status=status,
        notes="",
        confidence=80,
        reason="seed",
        updated_by="test",
    )
    # update_lead() computes lead_score itself from (status, confidence) via
    # calculate_lead_score - overwrite directly for tests that need a
    # specific, predictable score regardless of that formula.
    import database.db as db
    conn = db.get_crm_connection()
    conn.execute(
        "UPDATE leads SET lead_score = ? WHERE customer_phone = ?",
        (lead_score, customer_phone),
    )
    conn.commit()
    conn.close()


def test_evaluate_rule_list_format_is_implicit_and(isolated_db):
    _seed_customer("biz1", "biz1", "+10000000001", "+19990000001", lead_score=90, status="Qualified")
    _seed_customer("biz1", "biz1", "+10000000001", "+19990000002", lead_score=30, status="New")

    rule = {
        "name": "hot qualified leads",
        "condition_json": [
            {"field": "lead_score", "operator": ">=", "value": 80},
            {"field": "status", "operator": "=", "value": "Qualified"},
        ],
    }

    matched = evaluate_rule(rule, "biz1")

    assert [c["phone"] for c in matched] == ["+19990000001"]


def test_evaluate_rule_dict_or_format(isolated_db):
    _seed_customer("biz2", "biz2", "+10000000002", "+19990000003", lead_score=90, status="Qualified")
    _seed_customer("biz2", "biz2", "+10000000002", "+19990000004", lead_score=10, status="Closed Lost")

    rule = {
        "name": "hot or lost",
        "condition_json": {
            "logic": "OR",
            "conditions": [
                {"field": "lead_score", "operator": ">=", "value": 80},
                {"field": "status", "operator": "=", "value": "Closed Lost"},
            ],
        },
    }

    matched = evaluate_rule(rule, "biz2")

    assert {c["phone"] for c in matched} == {"+19990000003", "+19990000004"}


def test_evaluate_rule_legacy_operator_format(isolated_db):
    _seed_customer("biz3", "biz3", "+10000000003", "+19990000005", lead_score=85)
    _seed_customer("biz3", "biz3", "+10000000003", "+19990000006", lead_score=20)

    # FORMAT 3 (legacy): a bare {"operator": ..., "value": ...} implicitly
    # means "lead_score <operator> value".
    rule = {
        "name": "legacy hot leads",
        "condition_json": {"operator": ">=", "value": 50},
    }

    matched = evaluate_rule(rule, "biz3")

    assert [c["phone"] for c in matched] == ["+19990000005"]


def test_evaluate_rule_no_matches_returns_empty_list(isolated_db):
    _seed_customer("biz4", "biz4", "+10000000004", "+19990000007", lead_score=10)

    rule = {
        "name": "impossible",
        "condition_json": [{"field": "lead_score", "operator": ">=", "value": 999}],
    }

    assert evaluate_rule(rule, "biz4") == []


def test_evaluate_rule_accepts_a_prefetched_customer_list(isolated_db, monkeypatch):
    # automation/runner.py fetches get_customer_stats() once per business
    # and reuses it across every one of that business's rules, instead of
    # evaluate_rule() re-fetching it internally for every single rule -
    # passing `customers` explicitly must skip the internal fetch
    # entirely (not just override its result).
    _seed_customer("biz5", "biz5", "+10000000005", "+19990000008", lead_score=90, status="Qualified")

    def _fail_if_called(user_id):
        raise AssertionError(
            "get_customer_stats() should not be called when customers "
            "is passed explicitly"
        )

    monkeypatch.setattr(
        "automation.evaluator.get_customer_stats", _fail_if_called
    )

    prefetched = [{"phone": "+19990000008", "lead_score": 90, "status": "Qualified"}]

    rule = {
        "name": "prefetched",
        "condition_json": [{"field": "lead_score", "operator": ">=", "value": 80}],
    }

    matched = evaluate_rule(rule, "biz5", customers=prefetched)

    assert [c["phone"] for c in matched] == ["+19990000008"]
